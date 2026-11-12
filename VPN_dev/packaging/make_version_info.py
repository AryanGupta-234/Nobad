"""Write a PyInstaller VSVersionInfo file (shown in Explorer -> Properties -> Details):
    python packaging/make_version_info.py <version> packaging/version_info.txt"""
import re
import sys

ver, out = sys.argv[1], sys.argv[2]
nums = [int(x) for x in re.findall(r"\d+", ver)][:4]
nums += [0] * (4 - len(nums))
t = tuple(min(n, 65535) for n in nums)
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'NOBAD'),
      StringStruct('FileDescription', 'NOBAD VPN'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'NobadVPN'),
      StringStruct('LegalCopyright', 'Copyright (c) NOBAD'),
      StringStruct('OriginalFilename', 'NobadVPN.exe'),
      StringStruct('ProductName', 'NOBAD VPN'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print("wrote", out)
