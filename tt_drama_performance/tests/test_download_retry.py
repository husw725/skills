"""下载重试状态机自检。

镜像 daily_update.py run() 里导出下载那段循环的判定逻辑（最多 3 次，
崩了重开 context 再来，仍失败按 last_err 返回）。用假的下载动作驱动，
不依赖 playwright / 浏览器 / 平台。改主循环时同步改这里。
"""
class PWTimeout(Exception): pass
class PWError(Exception): pass   # TargetClosedError 属于此类

def simulate(download, reopen_ok=True, attempts=3):
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
print("OK: 6/6 断言通过")
