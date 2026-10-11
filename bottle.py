import asyncio
from http import HTTPStatus
from io import BytesIO
import random
from sqlite3 import Connection
import ssl
from typing import Any, Literal

import aiofiles
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from PIL import Image, ImageSequence

from .config import conf
from .data_deal import ID_FILE, IMAGE_PATH, PLUGIN_DATA


class NotSupportMessageError(Exception):
    """瓶子内容不支持的消息类型"""

    def __init__(self, *args: object):
        super().__init__(*args)


async def store_image_file(image_id: int, image_data: bytes) -> None:
    """存储图像数据到文件系统，使用有损压缩减小文件大小。

    如果是动图，则保存为动态 WebP，否则保存静态 WebP。

    参数:
        image_id: 图像对应的 ID
        image_data: 图像的二进制数据
    """
    image = Image.open(BytesIO(image_data))

    folder = IMAGE_PATH / str(image_id)
    folder.mkdir(parents=True, exist_ok=True)

    max_index = -1
    for file in folder.glob("*.webp"):
        try:
            max_index = max(max_index, int(file.stem))
        except ValueError:
            continue
    output_file = folder / f"{max_index + 1}.webp"

    is_animated = (
        getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1
    )
    if is_animated:
        frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
        frames[0].save(
            output_file,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=image.info.get("duration", 100),
            loop=0,
            quality=80,
        )
    else:
        image.save(output_file, format="WEBP", quality=80)

    logger.info(f"图像 ID {image_id} 成功保存为 {output_file}")


async def cache_file(msg: Message, image_id: int) -> None:
    """缓存消息中的图片数据到文件系统

    参数:
        msg: 消息
        image_id: 瓶子 ID
    """
    ssl_context = ssl.create_default_context()
    ssl_context.options |= ssl.OP_NO_SSLv3
    ssl_context.set_ciphers("HIGH:!DH:!aNULL")

    semaphore = asyncio.Semaphore(2)
    max_number = conf("MAX_BOTTLE_PIC", 2)
    async with httpx.AsyncClient(
        verify=ssl_context, timeout=30, limits=httpx.Limits(max_connections=5)
    ) as client:
        tasks = [
            cache_image_url(seg, client, image_id, semaphore)
            for i, seg in enumerate(msg)
            if seg.type == "image" and i < max_number
        ]
        await asyncio.gather(*tasks)


async def cache_image_url(
    seg: MessageSegment,
    client: httpx.AsyncClient,
    image_id: int,
    semaphore: asyncio.Semaphore,
) -> None:
    """缓存单个图片 URL 到文件系统"""
    async with semaphore:
        url = seg.data.get("url")
        if not url:
            return

        seg.type = "cached_image"
        seg.data.clear()
        try:
            r = await client.get(
                url, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
            )
            data = r.content
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"下载失败: {e}")
            return

        if r.status_code != HTTPStatus.OK or not data:
            return

        await store_image_file(image_id, data)
        seg.data = {"file": f"image_{image_id}"}


def validate_message(message: Message) -> None:
    """校验瓶子内容只包含文字与图片

    参数:
        message: 消息

    异常:
        NotSupportMessageError: 包含不支持的消息类型
    """
    for seg in message:
        if seg.type not in ("text", "image"):
            raise NotSupportMessageError("漂流瓶只支持文字和图片~")


async def cache_message(message: Message, image_id: int) -> None:
    """缓存瓶子消息中的图片

    参数:
        message: 消息
        image_id: 瓶子 ID
    """
    await cache_file(msg=message, image_id=image_id)


class Bottle:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_comments(self, id: int) -> str:
        """获取 comments 表中该瓶子的所有评论

        参数:
            id: 瓶子 ID

        返回:
            str: 'uid: content' 格式，换行分隔
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT uid, content FROM comments WHERE id = ?", (id,))
        rows = cursor.fetchall()
        cursor.close()
        if rows:
            return "\n".join(f"{row[0]}: {row[1]}" for row in rows)
        return ""

    async def add_comment(self, bottle_id: int, text: str, uid: str) -> bool:
        """评论瓶子，评论立即生效

        参数:
            bottle_id: 瓶子 ID
            text: 评论内容
            uid: 评论者 ID

        返回:
            bool: 瓶子是否存在
        """
        conn = self.conn
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM approved WHERE id = ?", (bottle_id,))
        if cursor.fetchone()[0] == 0:
            cursor.close()
            return False

        cursor.execute("SELECT MAX(comment_id) FROM comments")
        max_comment_id = cursor.fetchone()[0] or 0
        cursor.execute(
            "INSERT INTO comments (comment_id, id, content, uid) VALUES (?, ?, ?, ?)",
            (max_comment_id + 1, bottle_id, text, uid),
        )
        conn.commit()
        cursor.close()
        return True

    async def get_approved_bottle_by_id(self, bottle_id: int) -> dict[str, Any] | None:
        """根据 ID 获取一个漂流瓶

        参数:
            bottle_id: 瓶子 ID

        返回:
            dict[str, Any] | None: 瓶子信息
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, content, userid, groupid, timeinfo
            FROM approved
            WHERE id = ?
            """,
            (bottle_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if row:
            id, content, userid, groupid, timeinfo = row
            return {
                "id": id,
                "content": content,
                "userid": userid,
                "groupid": groupid,
                "timeinfo": timeinfo,
            }
        return None

    async def random_get_approves_bottle(self) -> None | dict[str, Any]:
        """随机获取一个漂流瓶

        返回:
            None | dict[str, Any]: 瓶子信息
        """
        conn = self.conn
        row_count = conn.execute("SELECT COUNT(*) FROM approved").fetchone()[0]
        if row_count == 0:
            return None

        random_index = random.randint(0, row_count - 1)
        row = conn.execute(
            """
            SELECT id, content, userid, groupid, timeinfo
            FROM approved
            LIMIT 1 OFFSET ?
            """,
            (random_index,),
        ).fetchone()

        if row:
            id, content, userid, groupid, timeinfo = row
            return {
                "id": id,
                "content": content,
                "userid": userid,
                "groupid": groupid,
                "timeinfo": timeinfo,
            }
        return None

    async def add_bottle(
        self, id: int, message: str, userid: str, groupid: str, timeinfo: str
    ) -> bool:
        """新增一个漂流瓶，直接进入可捡取状态

        参数:
            id: 瓶子 ID
            message: 瓶子内容
            userid: 发送者 ID
            groupid: 群组 ID
            timeinfo: 发送时间

        返回:
            bool: 是否添加成功
        """
        self.conn.execute(
            """
            INSERT INTO approved (id, content, userid, groupid, timeinfo, up)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (int(id), message, str(userid), str(groupid), str(timeinfo)),
        )
        self.conn.commit()
        return True

    async def up_bottle(
        self, bottle_id: int, uid: str
    ) -> tuple[Literal[False], None] | tuple[Literal[True], Any]:
        """点赞某个瓶子

        参数:
            bottle_id: 瓶子 ID
            uid: 点赞者 ID

        返回:
            tuple[Literal[False], None] | tuple[Literal[True], Any]:
                是否成功与最新点赞数
        """
        conn = self.conn
        cursor = conn.cursor()

        ids_list = []
        cursor.execute("SELECT ids FROM user_up WHERE uid = ?", (uid,))
        row = cursor.fetchone()
        if row:
            ids_list = row[0].split(",") if row[0] else []

        if str(bottle_id) in ids_list:
            cursor.close()
            return False, None

        cursor.execute("SELECT COUNT(*) FROM approved WHERE id = ?", (bottle_id,))
        if cursor.fetchone()[0] == 0:
            cursor.close()
            return False, None

        cursor.execute("SELECT up FROM approved WHERE id = ?", (bottle_id,))
        current_up_value = cursor.fetchone()[0] or 0
        cursor.execute(
            "UPDATE approved SET up = ? WHERE id = ?",
            (current_up_value + 1, bottle_id),
        )
        conn.commit()

        cursor.execute("SELECT up FROM approved WHERE id = ?", (bottle_id,))
        new_up_value = cursor.fetchone()[0]
        if new_up_value is None:
            cursor.close()
            return False, None

        ids_list.append(str(bottle_id))
        cursor.execute(
            "INSERT OR REPLACE INTO user_up (uid, ids) VALUES (?, ?)",
            (uid, ",".join(ids_list)),
        )
        conn.commit()
        cursor.close()

        return True, new_up_value

    async def get_bottle_images(self, id: int) -> list[bytes]:
        """获取指定 ID 的图片数据

        参数:
            id: 瓶子 ID

        返回:
            list[bytes]: 图片的二进制数据列表
        """
        image_folder = IMAGE_PATH / str(id)
        if not image_folder.exists() or not image_folder.is_dir():
            logger.warning(f"ID 为 {id} 的图片文件夹不存在！")
            return []

        images = []
        for image_file in sorted(image_folder.glob("*.webp")):
            try:
                async with aiofiles.open(image_file, "rb") as f:
                    images.append(await f.read())
            except Exception as e:
                logger.error(f"读取文件 {image_file} 时发生错误：{e}")

        return images


async def id_add() -> int:
    """获取下一个瓶子 ID

    返回:
        int: 瓶子 ID
    """
    PLUGIN_DATA.mkdir(exist_ok=True)

    if not ID_FILE.exists():
        async with aiofiles.open(ID_FILE, "w+", encoding="utf_8") as f:
            await f.write("0")

    async with aiofiles.open(ID_FILE, encoding="utf_8") as f:
        k = int(await f.read()) + 1

    async with aiofiles.open(ID_FILE, "w+", encoding="utf_8") as f:
        await f.write(str(k))

    return k
