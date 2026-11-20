"""Local, atomic user taxonomy, video assignments and bookmark folders."""
import copy
import difflib
import json
import os
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
PAGE = PROJECT / 'data/打开知识库.html'
STATE = PROJECT / 'data/workbench-personal.json'
LOCK = RLock()
SEEDS = [
    ('business', '商业与创业', '能力组合 商业基本功 护肤营销 离职创业 低成本试错 创业方向 商业机会 商业模式 一人公司 产业趋势 资源撮合 内容创业 电商运营 个人品牌 信息差 流量变现 用户需求 内容数据 短视频选题 产品定价 商业验证 赚钱路径 账号定位 社群运营 直播表达 创业案例 创作者访谈 镜头表达'),
    ('career', '职业与发展', '人生规划 职业方向 收入判断 求职方法 选专业 职场成长'),
    ('ai', 'AI与工具', 'AI办公 AI自学 AI写作 AI知识库'),
    ('learning', '学习与认知', '系统学习 阅读习惯 选书方法 输出式学习 长期决策 个人发展 自我接纳 历史阅读 读书笔记 自我认知 知识管理'),
    ('efficiency', '时间与行动', '时间管理 注意力管理 自我复盘 习惯养成 行动练习 目标管理'),
    ('relationships', '沟通与关系', '婚恋选择 社交圈选择 家庭沟通 人际边界 说服沟通'),
    ('finance', '理财与消费', '消费取舍 贷款判断 个人理财 投资思维'),
    ('health', '健康与情绪', '抗衰证据 肠道健康 焦虑应对'),
]
RULES = {
    'business': '创业 商业 营销 电商 产品 定价 用户 流量 变现 品牌 选题 直播 运营'.split(),
    'career': '职业 职场 求职 面试 简历 晋升 专业 离职'.split(),
    'ai': 'AI 人工智能 自动化 编程 代码 工具 软件 智能体'.split(),
    'learning': '学习 阅读 读书 认知 知识 思维 笔记 历史 决策'.split(),
    'efficiency': '时间 效率 计划 目标 执行 行动 习惯 专注 注意力 复盘'.split(),
    'relationships': '沟通 关系 家庭 婚恋 社交 朋友 人际 说服'.split(),
    'finance': '理财 投资 贷款 消费 储蓄 保险 借贷'.split(),
    'health': '健康 情绪 焦虑 睡眠 运动 饮食 抗衰 肠道 心理'.split(),
}


def normalize(text):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', text).casefold())


def label(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40 or any(ord(c) < 32 for c in value):
        raise ValueError('名称请填写 1 至 40 个字，不含换行')
    return value.strip()


def read_catalog(page=PAGE):
    content = page.read_text('utf-8')
    match = re.search(r'<script id="catalog"[^>]*>(.*?)</script>', content, re.S)
    if not match:
        raise ValueError('找不到个人工作台的作品目录')
    return json.loads(match.group(1))


class LibraryState:
    def __init__(self, path=STATE, page=PAGE):
        self.path, self.page = Path(path), Path(page)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with LOCK, self.path.with_suffix('.lock').open('a+b') as handle:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0'); handle.flush()
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                exists = self.path.exists()
                state = json.loads(self.path.read_text('utf-8')) if exists else self.initial()
                before = copy.deepcopy(state)
                yield state
                if not exists or state != before:
                    state['revision'] += 1
                    target = self.path.with_suffix(f'.{os.getpid()}.tmp')
                    target.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', 'utf-8')
                    if exists:
                        self.path.with_suffix('.bak').write_bytes(self.path.read_bytes())
                    target.replace(self.path)
            finally:
                if os.name == 'nt':
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def initial(self):
        state = {'version': 1, 'revision': 0, 'groups': {}, 'groupAliases': {}, 'topics': {}, 'aliases': {},
                 'assignments': {}, 'folders': {'default': {'name': '未分组收藏', 'items': []}}}
        for key, name, words in SEEDS:
            state['groups'][key] = {'name': name}
            for topic in words.split():
                state['topics'][topic] = {'name': topic, 'group': key, 'state': 'confirmed'}
        state['groups']['pending'] = {'name': '待归类小主题'}
        # Existing published material is the migration baseline, not a new import.
        if self.page.is_file():
            for video in read_catalog(self.page)['videos']:
                state['assignments'][video['id']] = {'mode': 'auto', 'confirmed': True}
        return state

    @staticmethod
    def resolve(state, key):
        seen = set()
        while key in state['aliases'] and key not in seen:
            seen.add(key); key = state['aliases'][key]
        return key

    def ensure_topic(self, state, name):
        key = self.resolve(state, name)
        if key in state['topics']:
            return key
        same = next((key for key, topic in state['topics'].items() if normalize(topic['name']) == normalize(name)), None)
        if same:
            state['aliases'][name] = same
            return same
        possible = [(difflib.SequenceMatcher(None, normalize(name), normalize(t['name'])).ratio(), key)
                    for key, t in state['topics'].items()]
        score, similar = max(possible, default=(0, ''))
        scores = {}
        for key, words in RULES.items():
            while key in state.get('groupAliases', {}):
                key = state['groupAliases'][key]
            if key in state['groups']:
                scores[key] = scores.get(key, 0) + sum(word.casefold() in name.casefold() for word in words)
        high = max(scores.values(), default=0)
        groups = [key for key, score in scores.items() if score == high and score]
        group = groups[0] if len(groups) == 1 else 'pending'
        reason = '疑似与已有小主题重复' if score >= .70 else '归属需要确认' if group == 'pending' else ''
        state['topics'][name] = {'name': name, 'group': group if not reason else 'pending',
                                 'state': 'pending' if reason else 'confirmed', 'reason': reason,
                                 'suggestedGroup': group, 'similar': similar if score >= .70 else ''}
        return name

    def sync(self, catalog=None):
        catalog = catalog or read_catalog(self.page)
        with self.transaction() as state:
            for video in catalog['videos']:
                for tag in video.get('tags', []):
                    self.ensure_topic(state, tag)
            result = self.project(state, catalog)
        result['revision'] = state['revision']
        return result

    def project(self, state, catalog):
        result = copy.deepcopy(state)
        result['videos'] = {}
        for video in catalog['videos']:
            ident = video['id']
            if state.get('deletions', {}).get(ident, {}).get('record'):
                continue
            original = list(dict.fromkeys(self.resolve(state, tag) for tag in video.get('tags', [])))
            setting = state['assignments'].get(ident, {'mode': 'choose', 'confirmed': False})
            chosen = [self.resolve(state, key) for key in setting.get('topics', original)]
            chosen = list(dict.fromkeys(key for key in chosen if key in state['topics']))
            uncertain = [key for key in chosen if state['topics'][key]['state'] == 'pending']
            pending = not setting.get('confirmed') and setting['mode'] != 'auto' or bool(uncertain)
            ready = bool(video.get('transcript') or video.get('core'))
            result['videos'][ident] = {'suggested': original, 'topics': [] if pending else chosen,
                                       'mode': setting['mode'], 'pending': bool(pending and ready),
                                       'reason': '请选择自动归属或手动确认' if setting['mode'] == 'choose' else
                                                 '新小主题需要确认' if uncertain else '等待你确认推荐归属' if pending else ''}
        # Canonicalize favorites after merges; keep originals on disk for stable migration.
        for folder in result['folders'].values():
            items = [(kind, self.resolve(state, ident) if kind == 'topic' else ident) for kind, ident in folder['items']]
            folder['items'] = [list(item) for item in dict.fromkeys(items)]
        return result

    def effective_catalog(self, catalog):
        """Apply deletion choices before embedding a rebuilt static page."""
        with self.transaction() as state:
            return self.mask_catalog(catalog, state.get('deletions', {}))

    @staticmethod
    def mask_catalog(catalog, deletions):
        result = copy.deepcopy(catalog)
        result['videos'] = [video for video in result['videos'] if not deletions.get(video['id'], {}).get('record')]
        for video in result['videos']:
            flags = deletions.get(video['id'], {})
            if flags.get('media'):
                video.update(local='', hasCompressedVideo=False)
            if flags.get('transcript'):
                video.update(transcript='', subtitle='', subtitleTimes=[])
            if flags.get('summary'):
                video.update(core='', points=None, pointDisplay={})
        return result

    def deleted_records(self):
        if not self.path.is_file():
            return set()
        with self.transaction() as state:
            return {key for key, flags in state.get('deletions', {}).items() if any(flags.get(kind) for kind in ('record', 'media', 'summary', 'transcript'))}

    def restore_import(self, ids):
        with self.transaction() as state:
            for ident in ids:
                state.get('deletions', {}).pop(ident, None)

    def mark_import(self, ids, mode):
        if mode not in ('auto', 'manual'):
            raise ValueError('请为本批视频选择自动归属或推荐后手动确认')
        with self.transaction() as state:
            for ident in ids:
                # Reimporting must not erase an existing human decision.
                state['assignments'].setdefault(ident, {'mode': mode, 'confirmed': False})

    def vocabulary(self):
        with self.transaction() as state:
            return {key for key, topic in state['topics'].items() if topic['state'] == 'confirmed'} | {
                topic['name'] for topic in state['topics'].values() if topic['state'] == 'confirmed'} | set(state['aliases'])

    def act(self, payload, catalog=None):
        catalog = catalog or read_catalog(self.page)
        action = payload.get('action', 'state')
        if action == 'state':
            return self.sync(catalog)
        if action == 'video.delete':
            from deletion import delete_selected
            return delete_selected(self, payload, catalog)
        valid_videos = {v['id'] for v in catalog['videos']}
        with self.transaction() as state:
            if payload.get('revision') is not None and payload['revision'] != state['revision']:
                raise ValueError('内容已被其他页面更新，请刷新后再操作')
            key = payload.get('id', '')
            if action in ('group.create', 'folder.create'):
                collection = state['groups' if action.startswith('group') else 'folders']
                name = label(payload.get('name'))
                if any(normalize(row['name']) == normalize(name) for row in collection.values()):
                    raise ValueError('这个名称已经存在')
                collection[uuid4().hex[:12]] = {'name': name, **({'items': []} if action.startswith('folder') else {})}
            elif action in ('group.rename', 'folder.rename', 'topic.rename'):
                collection = state[{'group': 'groups', 'folder': 'folders', 'topic': 'topics'}[action.split('.')[0]]]
                if key not in collection or key == 'pending':
                    raise ValueError('找不到可改名的项目')
                name = label(payload.get('name'))
                if any(ident != key and normalize(row['name']) == normalize(name) for ident, row in collection.items()):
                    raise ValueError('这个名称已存在，请使用合并功能')
                if action == 'topic.rename':
                    alias = self.resolve(state, name)
                    if name in state['aliases'] and alias != key:
                        raise ValueError('这个名称属于已有主题的别名，请换一个名称或合并')
                    old_name = collection[key]['name']
                    if old_name != key:
                        state['aliases'][old_name] = key
                    state['aliases'][name] = key
                collection[key]['name'] = name
            elif action == 'folder.delete':
                if key == 'default' or key not in state['folders']:
                    raise ValueError('未分组收藏保留，其他收藏夹可以删除')
                del state['folders'][key]
            elif action == 'favorite.set':
                kind = payload.get('kind')
                if kind == 'topic':
                    key = self.resolve(state, key)
                if kind not in ('topic', 'video') or key not in (state['topics'] if kind == 'topic' else valid_videos):
                    raise ValueError('收藏对象不存在')
                folders = payload.get('folders')
                if not isinstance(folders, list) or any(f not in state['folders'] for f in folders):
                    raise ValueError('收藏夹不存在，请刷新')
                for ident, folder in state['folders'].items():
                    folder['items'] = [item for item in folder['items'] if not (item[0] == kind and (self.resolve(state, item[1]) if kind == 'topic' else item[1]) == key)]
                    if ident in folders:
                        folder['items'].append([kind, key])
            elif action in ('group.merge', 'topic.merge'):
                kind = action.split('.')[0]
                collection = state['groups' if kind == 'group' else 'topics']
                target = payload.get('target')
                if key not in collection or target not in collection or key == target or 'pending' in (key, target):
                    raise ValueError('请选择两个不同的有效主题')
                if kind == 'group':
                    state.setdefault('groupAliases', {})[key] = target
                    for topic in state['topics'].values():
                        if topic['group'] == key:
                            topic['group'] = target
                else:
                    if collection[target]['state'] != 'confirmed':
                        raise ValueError('请先确认目标小主题的归属')
                    state['aliases'][key] = target
                    state['aliases'][collection[key]['name']] = target
                del collection[key]
            elif action == 'topic.move':
                group = payload.get('group')
                if key not in state['topics'] or group not in state['groups'] or group == 'pending':
                    raise ValueError('请选择有效的大主题')
                state['topics'][key].update(group=group, state='confirmed', reason='', similar='')
            elif action in ('video.assign', 'video.auto'):
                ids = payload.get('ids', [key])
                if not isinstance(ids, list) or not ids or any(ident not in valid_videos for ident in ids):
                    raise ValueError('请选择有效的视频')
                if action == 'video.assign':
                    tags = payload.get('topics', [])
                    tags = list(dict.fromkeys(self.resolve(state, tag) for tag in tags))
                    if not 1 <= len(tags) <= 6 or any(tag not in state['topics'] or state['topics'][tag]['state'] != 'confirmed' for tag in tags):
                        raise ValueError('请选择 1 至 6 个已归类的小主题')
                    for ident in ids:
                        state['assignments'][ident] = {'mode': 'manual', 'confirmed': True, 'topics': tags}
                else:
                    for ident in ids:
                        state['assignments'][ident] = {'mode': 'auto', 'confirmed': False}
            else:
                raise ValueError('不支持这个整理操作')
            result = self.project(state, catalog)
        result['revision'] = state['revision']
        return result
