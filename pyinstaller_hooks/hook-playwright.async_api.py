from PyInstaller.utils.hooks import collect_data_files

datas = [
    (src, dest)
    for src, dest in collect_data_files("playwright")
    if ".local-browsers" not in (src + "\\" + dest).lower()
]
