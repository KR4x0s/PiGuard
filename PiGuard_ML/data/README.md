# Data provenance

- `domains_features.gz` is downloaded from https://github.com/tisage/DGA-dataset at revision `b9c75bc92d16736875f094b05180befb163d756a`. Training records its actual row count and SHA-256; the source ZIP excludes the data download. See `DGA_DATASET_LICENSE.txt` and cite the repository's associated paper, *A Dictionary-Based Method for Detecting Machine-Generated Domains*, Wang, Chen & Genc (2021), DOI 10.1080/19393555.2020.1834650.
- `public_suffix_list.dat` was fetched from https://publicsuffix.org/list/public_suffix_list.dat on 2026-10-25. Its embedded header includes upstream version, commit, and MPL-2.0 notice. Candidate contracts bind the exact file hash. Runtime extraction uses only the ICANN section and never downloads an update.
- Updating the suffix snapshot or normalization requires a new preprocessing contract and a new training run. Do not replace a snapshot inside an existing release.
