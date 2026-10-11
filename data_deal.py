from io import BytesIO
import sqlite3

from nonebot import get_driver, logger
from PIL import Image, UnidentifiedImageError

from zhenxun.configs.path_config import DATA_PATH

PLUGIN_DATA = DATA_PATH / "web_bottle"
"""插件数据目录"""

IMAGE_PATH = PLUGIN_DATA / "img"
"""瓶子图片目录"""

DB_PATH = PLUGIN_DATA / "bottle.db"
"""sqlite 数据库路径"""

ID_FILE = PLUGIN_DATA / "bottle_id.txt"
"""瓶子自增 id 文件"""

PLUGIN_DATA.mkdir(parents=True, exist_ok=True)
IMAGE_PATH.mkdir(parents=True, exist_ok=True)

drive = get_driver()
conn_bottle: sqlite3.Connection


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    """迁移旧版本的数据库结构

    参数:
        conn: 数据库连接
    """
    cursor = conn.cursor()

    # 旧版的待审表 pending：现在免审核，直接并入 approved
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pending'"
    )
    if cursor.fetchone():
        logger.info("检测到待审表 pending，正在并入 approved 表...")
        cursor.execute(
            """
            INSERT OR IGNORE INTO approved (id, content, userid, groupid, timeinfo, up)
            SELECT id, content, userid, groupid, timeinfo, 0 FROM pending
            """
        )
        cursor.execute("DROP TABLE pending")
        conn.commit()
        logger.success("pending 表已并入 approved 并删除")

    # 更早版本的 images 二进制表：落盘为 webp 文件
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='images'"
    )
    if not cursor.fetchone():
        cursor.close()
        return

    logger.info("检测到 images 表，正在迁移图片数据，请稍候...")
    cursor.execute("SELECT id, data FROM images")
    for image_id, image_data in cursor.fetchall():
        if not image_data:
            logger.warning(f"ID 为 {image_id} 的图片数据为空，跳过迁移！")
            continue
        target_dir = IMAGE_PATH / str(image_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            image = Image.open(BytesIO(image_data)).convert("RGB")
            max_index = -1
            for file in target_dir.glob("*.webp"):
                try:
                    max_index = max(max_index, int(file.stem.split("_")[-1]))
                except ValueError:
                    continue
            image.save(
                target_dir / f"image_{max_index + 1}.webp", format="WEBP", quality=80
            )
            logger.info(f"成功迁移 ID 为 {image_id} 的图片")
        except UnidentifiedImageError:
            logger.error(f"ID 为 {image_id} 的数据不是有效图片，跳过迁移！")
        except Exception as e:
            logger.error(f"迁移 ID 为 {image_id} 的图片时发生未知错误：{e}")

    cursor.execute("DROP TABLE images")
    conn.commit()
    cursor.close()
    logger.success("images 表已删除，数据迁移成功！")


@drive.on_startup
def _():
    """初始化漂流瓶数据库"""
    if not DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE approved (
                id INTEGER PRIMARY KEY,
                content TEXT,
                userid TEXT,
                groupid TEXT,
                timeinfo TEXT,
                up INTEGER
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE comments (
                comment_id INTEGER PRIMARY KEY,
                id INTEGER,
                content TEXT,
                uid TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE user_up (
                uid INTEGER PRIMARY KEY UNIQUE,
                ids TEXT
            )
            """
        )
        conn.commit()
        conn.close()
        logger.success("漂流瓶数据库和表成功创建！")
    else:
        conn = sqlite3.connect(DB_PATH)
        _migrate_legacy(conn)
        conn.close()
        logger.info("漂流瓶数据库已存在，跳过创建步骤！")

    global conn_bottle
    conn_bottle = sqlite3.connect(DB_PATH, check_same_thread=False)
    logger.info(f"漂流瓶插件数据存储目录: {PLUGIN_DATA}")
