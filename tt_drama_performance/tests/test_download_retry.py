"""下载重试状态机自检。

镜像 daily_update.py run() 里导出下载那段循环的判定逻辑（最多 3 次，
崩了重开 context 再来，仍失败按 last_err 返回）。用假的下载动作驱动，
不依赖 playwright / 浏览器 / 平台。改主循环时同步改这里。
"""
class PWTimeout(Exception): pass
class PWError(Exception): pass   # TargetClosedError 属于此类

def simulate(download, reopen_ok=True, attempts=3, purge=lambda: None):
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            download()
            last_err = None
            break
        except PWTimeout:
            last_err = 'timeout'
        except PWError:
            last_err = 'closed'
        if attempt < attempts:
            if last_err == 'closed':     # 崩溃 -> 重开前清掉 profile 脏库（shared_proto_db）
                purge()
            if not reopen_ok:            # 重开时登录态失效 -> 放弃
                last_err = 'timeout'
                break
    return last_err

def maker(fail_times, exc):
    n = {'i': 0}
    def dl():
        if n['i'] < fail_times:
            n['i'] += 1
            raise exc()
    return dl

assert simulate(maker(0, PWError)) is None            # 一次成功
assert simulate(maker(1, PWError)) is None            # 崩1次后自愈(原来会崩掉整个脚本)
assert simulate(maker(2, PWError)) is None            # 崩2次后自愈
assert simulate(maker(3, PWError)) == 'closed'        # 连崩3次 -> closed 退出
assert simulate(maker(3, PWTimeout)) == 'timeout'     # 连超时3次 -> timeout
assert simulate(maker(3, PWError), reopen_ok=False) == 'timeout'  # 重开时登录失效

# profile 脏库场景（2026-09-20 实测）：只要脏库还在，每次下载必崩；清掉才好。
def poisoned():
    st = {'bad': True, 'purged': 0}
    def dl():
        if st['bad']:
            raise PWError()
    def purge():
        st['purged'] += 1
        st['bad'] = False
    return dl, purge, st

dl, purge, st = poisoned()
assert simulate(dl, purge=purge) is None and st['purged'] == 1   # 崩1次 -> 清库 -> 第2次成功
dl, _, st = poisoned()
assert simulate(dl) == 'closed'                                   # 不清库 -> 3次全撞墙（修复前的行为）
dl, purge, st = poisoned()
assert simulate(maker(3, PWTimeout), purge=purge) == 'timeout' and st['purged'] == 0  # 超时不清库
print("OK: 9/9 断言通过")
