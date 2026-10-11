import base64

from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .bottle import Bottle
from .config import conf


async def botte_routing(bot: Bot, bottle_data: dict, bottle: Bottle) -> list:
    """获取瓶子内容、评论，并以列表形式返回

    参数:
        bot: Bot
        bottle_data: 瓶子数据
        bottle: Bottle 实例

    返回:
        list: 消息列表
    """
    return await get_botte_all(bot, bottle_data, bottle)


async def get_botte_all(bot: Bot, bottle_data: dict, bottle: Bottle) -> list:
    """获取瓶子内容、评论，并以列表形式返回"""
    message = []

    msg_one = f"漂流瓶ID：{bottle_data['id']}\n内容：{bottle_data['content']}\n"
    if conf("BOTTLE_MSG_UNAME", True):
        msg_one += f"发送者：{await get_user_name(bot, bottle_data['userid'])}\n"
    if conf("BOTTLE_MSG_GNAME", True):
        msg_one += f"发送群：{await get_group_name(bot, bottle_data['groupid'])}\n"
    msg_one += f"发送时间：{bottle_data['timeinfo']}"
    msg_one = Message(msg_one)

    for img_bytes in await bottle.get_bottle_images(bottle_data["id"]):
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")
        msg_one += MessageSegment.image(f"base64://{img_base64}")

    message.append(msg_one)

    comments = await bottle.get_comments(int(bottle_data["id"]))
    if comments:
        formatted_comments = await format_comments(bot, comments)
        if conf("BOTTLE_MSG_SPLIT", True):
            message.append(formatted_comments)
        else:
            message[0] += Message(formatted_comments)

    return message


async def get_user_name(bot: Bot, user_id: int) -> str:
    """获取用户昵称

    参数:
        bot: Bot
        user_id: 用户 ID

    返回:
        str: 昵称，获取失败时返回用户 ID
    """
    try:
        user_info = await bot.call_api(api="get_stranger_info", user_id=user_id)
        return user_info["nickname"]
    except Exception:
        return str(user_id)


async def get_group_name(bot: Bot, group_id: int) -> str:
    """获取群名称

    参数:
        bot: Bot
        group_id: 群组 ID

    返回:
        str: 群名称，获取失败时返回群组 ID
    """
    try:
        group_info = await bot.call_api(api="get_group_info", group_id=group_id)
        return group_info["group_name"]
    except Exception:
        return str(group_id)


async def format_comments(bot: Bot, comments: str) -> str:
    """格式化评论

    参数:
        bot: Bot
        comments: 'uid: content' 格式的评论

    返回:
        str: 格式化后的评论
    """
    max_bottle_comments = conf("MAX_BOTTLE_COMMENTS", 3)
    bottle_msg_uname = conf("BOTTLE_MSG_UNAME", True)
    default_nickname = conf("DEFAULT_NICKNAME", "未知昵称")

    formatted_comments = "评论区：\n"
    comment_count = 0

    for line in comments.split("\n"):
        if comment_count >= max_bottle_comments:
            break
        user_id, comment = line.split(": ", 1)
        user_name = (
            await get_user_name(bot, int(user_id))
            if bottle_msg_uname
            else default_nickname
        )
        formatted_comments += f"{user_name}: {comment}\n"
        comment_count += 1

    return formatted_comments
