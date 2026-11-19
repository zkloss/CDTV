from PyInstaller.utils.hooks import collect_data_files

# Playwright 的 Node 驱动必须保留；浏览器本体由外部 runtime/chrome-win64 提供，
# 排除重复的 .local-browsers 可显著减小安装包体积。
datas = [
    (src, dest)
    for src, dest in collect_data_files("playwright")
    if ".local-browsers" not in (src + "\\" + dest).lower()
]
