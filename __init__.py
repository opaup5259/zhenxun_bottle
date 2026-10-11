from datetime import datetime
import re

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from zhenxun.configs.utils import (
    Command,
    Example,
    PluginCdBlock,
    PluginExtraData,
    PluginSetting,
    RegisterConfig,
)

from . import data_deal
from .bottle import (
    Bottle,
    NotSupportMessageError,
    cache_message,
    id_add,
    validate_message,
)
from .config import MODULE_NAME, conf
from .to_msg import botte_routing

__plugin_meta__ = PluginMetadata(
    name="漂流瓶",
    description="往群里扔出或捡起漂流瓶的群内小游戏，支持图片、点赞与评论。",
    usage="""
    扔瓶子 [图片/文本]        扔一个漂流瓶进大海
    捡瓶子                     随机捞起一个漂流瓶
    查看漂流瓶 [编号]          查看指定漂流瓶
    评论漂流瓶 [编号] [内容]    给漂流瓶留言
    点赞漂流瓶 [编号]          给漂流瓶点赞
    漂流瓶 / 漂流瓶菜单         查看帮助
    """.strip(),
    type="application",
    homepage="https://github.com/luosheng520qaq/nonebot-plugin-web-bottle",
    supported_adapters={"~onebot.v11"},
    extra=PluginExtraData(
        author="luosheng520qaq",
        version="0.2",
        menu_type="群内小游戏",
        introduction="把想说的话装进瓶子扔进大海，等待有缘人捡起。",
        commands=[
            Command(
                command="丢瓶子",
                params=["[图片/文本]"],
                description="扔一个漂流瓶进大海",
                examples=[
                    Example(exec="扔瓶子 今天天气真好", description="扔出文字瓶子"),
                    Example(exec="扔瓶子（附带图片）", description="扔出带图的瓶子"),
                ],
            ),
            Command(
                command="捡瓶子",
                description="随机捞起一个漂流瓶",
            ),
            Command(
                command="查看漂流瓶",
                params=["[编号]"],
                description="查看指定漂流瓶",
                examples=[Example(exec="查看漂流瓶 3")],
            ),
            Command(
                command="评论漂流瓶",
                params=["[编号]", "[内容]"],
                description="给漂流瓶留言",
                examples=[Example(exec="评论漂流瓶 3 加油鸭")],
            ),
            Command(
                command="点赞漂流瓶",
                params=["[编号]"],
                description="给漂流瓶点赞",
                examples=[Example(exec="点赞漂流瓶 3")],
            ),
            Command(
                command="漂流瓶",
                description="查看漂流瓶帮助",
            ),
        ],
        configs=[
            RegisterConfig(
                module=MODULE_NAME,
                key="MAX_BOTTLE_PIC",
                value=2,
                default_value=2,
                type=int,
                help="丢瓶子时允许附带的最大图片数量",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="MAX_BOTTLE_LINES",
                value=9,
                default_value=9,
                type=int,
                help="丢瓶子时允许的最大文本行数",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="MAX_BOTTLE_WORD",
                value=1200,
                default_value=1200,
                type=int,
                help="丢瓶子时允许的最大字符数量",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="EMBEDDED_HELP",
                value=True,
                default_value=True,
                type=bool,
                help="丢瓶子未填写任何内容时，是否回复指令帮助",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="DEFAULT_NICKNAME",
                value="未知昵称",
                default_value="未知昵称",
                type=str,
                help="获取昵称失败时评论区用户的默认称呼",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="BOTTLE_MSG_SPLIT",
                value=True,
                default_value=True,
                type=bool,
                help="瓶子内容与评论区是否分为两条消息发送",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="MAX_BOTTLE_COMMENTS",
                value=3,
                default_value=3,
                type=int,
                help="捡瓶子时最多展示的评论条数",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="BOTTLE_MSG_UNAME",
                value=True,
                default_value=True,
                type=bool,
                help="是否展示发送者昵称（官方Bot或追求速度时可关闭）",
            ),
            RegisterConfig(
                module=MODULE_NAME,
                key="BOTTLE_MSG_GNAME",
                value=True,
                default_value=True,
                type=bool,
                help="是否展示来源群名称（官方Bot或追求速度时可关闭）",
            ),
        ],
        setting=PluginSetting(default_status=True, level=5),
        limits=[PluginCdBlock(cd=6)],
    ).to_dict(),
)

bottle_help_text = __plugin_meta__.usage

throw = on_command("丢瓶子", aliases={"扔瓶子"}, priority=5, block=True)
get_bottle = on_command("捡瓶子", aliases={"捡漂流瓶"}, priority=5, block=True)
up_bottle = on_command("点赞漂流瓶", priority=5, block=True)
comment = on_command("评论漂流瓶", priority=5, block=True)
read_bottle = on_command("查看漂流瓶", priority=5, block=True)
bottle_help = on_command("漂流瓶", aliases={"漂流瓶菜单"}, priority=5, block=True)


@bottle_help.handle()
async def _():
    await bottle_help.finish("\n漂流瓶使用帮助" + bottle_help_text)


@read_bottle.handle()
async def _(event: GroupMessageEvent, bot: Bot, foo: Message = CommandArg()):
    try:
        bottle_id = int(foo.extract_plain_text())
    except ValueError:
        await read_bottle.finish("请输入正确的漂流瓶id")

    bottle = Bottle(data_deal.conn_bottle)
    bottle_data = await bottle.get_approved_bottle_by_id(bottle_id)
    if bottle_data is None:
        await read_bottle.finish("漂流瓶不存在")

    for message in await botte_routing(bot, bottle_data, bottle):
        await read_bottle.send(message)
    await read_bottle.finish()


@comment.handle()
async def _(event: GroupMessageEvent, foo: Message = CommandArg()):
    try:
        args = str(foo).split(maxsplit=1)
        bottle_id = int(args[0])
        text = str(foo)[len(args[0]) :].strip()
    except ValueError:
        await comment.finish("请输入正确的漂流瓶id和评论内容")
    except IndexError:
        await comment.finish("请输入评论内容")

    bottle = Bottle(data_deal.conn_bottle)
    if await bottle.add_comment(bottle_id, text, str(event.user_id)):
        await comment.finish("评论成功！")
    await comment.finish("评论失败，漂流瓶不存在")


@up_bottle.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    try:
        bid = int(args.extract_plain_text())
    except ValueError:
        await up_bottle.finish("请输入正确的漂流瓶id")

    bottle = Bottle(data_deal.conn_bottle)
    ok, num = await bottle.up_bottle(bid, str(event.user_id))
    if not ok:
        await up_bottle.finish("点赞失败，漂流瓶不存在或你已经点赞过了")
    await up_bottle.finish(f"点赞成功,现在有{num}个赞！")


@get_bottle.handle()
async def _(event: GroupMessageEvent, bot: Bot):
    bottle = Bottle(data_deal.conn_bottle)
    bottle_data = await bottle.random_get_approves_bottle()
    if not bottle_data:
        await get_bottle.finish("捞瓶子失败，没有漂流瓶~")

    for message in await botte_routing(bot, bottle_data, bottle):
        await get_bottle.send(message)
    await get_bottle.finish()


@throw.handle()
async def _(event: GroupMessageEvent, args: Message = CommandArg()):
    max_bottle_word = conf("MAX_BOTTLE_WORD", 1200)
    max_bottle_lines = conf("MAX_BOTTLE_LINES", 9)
    max_bottle_pic = conf("MAX_BOTTLE_PIC", 2)

    if not args:
        if conf("EMBEDDED_HELP", True):
            await throw.finish(
                f"您还没有写好瓶子的内容哦~\n漂流瓶食用方法：{bottle_help_text}"
            )
        await throw.finish("您还没有写好瓶子的内容哦~")

    content = args.extract_plain_text().strip()
    if len(content) > max_bottle_word:
        await throw.finish(f"丢瓶子失败啦，请不要超过{max_bottle_word}字符哦~")

    msg = event.get_message()
    if len(re.findall(r"[\r\n]+", content)) > max_bottle_lines:
        await throw.finish(f"丢瓶子失败啦，请不要超过{max_bottle_lines}行内容哦~")
    if sum(1 for seg in msg if seg.type == "image") > max_bottle_pic:
        await throw.finish(f"丢瓶子失败啦，请不要超过{max_bottle_pic}张图片哦~")

    try:
        validate_message(msg)
    except NotSupportMessageError as e:
        await throw.finish(str(e))

    bid = await id_add()
    await cache_message(msg, bid)

    bottle = Bottle(data_deal.conn_bottle)
    time_info = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if await bottle.add_bottle(
        bid, content, str(event.user_id), str(event.group_id), time_info
    ):
        await throw.finish(f"丢瓶子成功！瓶子ID是:{bid}")
    await throw.finish("丢瓶子失败啦，出现未知异常")
