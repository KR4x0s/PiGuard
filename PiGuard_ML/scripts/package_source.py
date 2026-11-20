#!/usr/bin/env python3
"""Package reviewed source only; never include local logs, state, credentials, or environments."""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
output=root/'output'
output.mkdir(exist_ok=True)
files=[root/name for name in ['README.md','IMPLEMENTATION_STATUS.md','requirements.txt','requirements-dev.txt',
 'requirements.lock','piguard_dga_features.py','piguard_dga_inference.py','test_features.py','PiGuard_DGA_Training_Colab.ipynb']]
for directory in ['piguard','tests','scripts','deploy']:
 files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
files.extend(root/'data'/name for name in ['public_suffix_list.dat','DGA_DATASET_LICENSE.txt','README.md'])
path=output/'PiGuard_ML_Source.zip'
with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
 for file in sorted(set(files)):
  z.write(file,file.relative_to(root))
print(path)
