# PiGuard: Integrated Raspberry Pi Network Security Gateway & DGA Detection Appliance

PiGuard is an integrated, hardware-hardened network security appliance and privacy gateway engineered for the **Raspberry Pi 3B+** (ARM64). It bridges DNS-level content filtering, stateful packet filtering, transparent Tor privacy routing, and an asynchronous, machine-learning-based Domain Generation Algorithm (DGA) detection engine.

Designed for edge deployment, PiGuard operates within strict physical resource budgets (1 GB RAM, quad-core Cortex-A53) and enforces least-privilege security boundaries between user-facing web services and low-level kernel networking controls.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Dual Topology Operation](#dual-topology-operation)
   - [Home Hotspot Mode](#1-home-hotspot-mode-active)
   - [Travel / Public Wi-Fi Mode](#2-travel--public-wi-fi-mode)
   - [Gateway Traffic Modes](#gateway-traffic-modes)
3. [Repository Structure](#repository-structure)
4. [Feature Folders Deep Dive](#feature-folders-deep-dive)
   - [PiGuard Network Gateway Subsystem](#piguard-network-gateway-subsystem)
   - [PiGuard ML Subsystem](#piguard-ml-subsystem)
5. [Machine Learning Pipeline & Metrics](#machine-learning-pipeline--metrics)
   - [Feature Contract v3.0.0](#feature-contract-v300)
   - [Resource Budgets & Model Selection](#resource-budgets--model-selection)
   - [Held-Out Evaluation Results](#held-out-evaluation-results)
6. [Security & Isolation Architecture](#security--isolation-architecture)
7. [Deployment & Verification Workflow](#deployment--verification-workflow)
8. [Troubleshooting & Recovery](#troubleshooting--recovery)

---

## System Architecture

```text
                               +-----------------------------------------------------------------------------+
                               |                            Raspberry Pi 3B+ (ARM64)                         |
                               |                                                                             |
[ Downstream Clients ]         |  +-------------------+        +--------------------+                        |         [ Internet ]
(Laptops, Mobile Devices)      |  |   Nginx Ingress   |        |  Flask Dashboard   |                        |              ^
       |                       |  |  (HTTPS 10.78.0.1)| <----> |  (Loopback 8080)   |                        |              |
       | Ethernet / Wi-Fi AP   |  +---------+---------+        +---------+----------+                        |              |
       v                       |            |                            |                                   |              |
[ 10.78.0.1/24 Downlink ] ---->|     [ nftables Guard ]                  v Unix Socket (/run/piguard-control)|              |
       |                       |     (Table: inet piguard_gateway)  [ Root Broker (control_broker.py) ]      |              |
       |                       |            |                            |                                   |              |
       +--- Port 53 (DNS) ---->|            v                            v Fixed Actions Only                |              |
       |                       |     +--------------+              [ Gateway CLI (gateway.py) ]              |              |
       |                       |     | Pi-hole Core |                                                        |              |
       |                       |     |   v6 / FTL   |                                                        |              |
       |                       |     +-------+------+                                                        |              |
       |                       |             |                                                               |              |
       |                       |             | Asynchronous Poll (Read-Only SQLite)                          |              |
       |                       |             v                                                               |              |
       |                       |     +---------------------------------------------------------+             |              |
       |                       |     |              PiGuard ML Observer Subsystem              |             |              |
       |                       |     |  * LRU Cache (10k entries)                              |             |              |
       |                       |     |  * Feature Extraction Contract v3                       |             |              |
       |                       |     |  * Evaluated Compact Forest (178 MiB RSS)               |             |              |
       |                       |     |  * Alert Store (/var/lib/piguard/state.db)              |             |              |
       |                       |     +---------------------------------------------------------+             |              |
       |                       |                                                                             |              |
       |                       |  Traffic Routing Path:                                                      |              |
       +--- TCP Forwarding --->|  * Normal Mode: Uplink NAT (IPv4 Masquerade) -------------------------------+------------->+ (Direct)
                               |  * Tor Mode:    Redirect to Tor TransPort (TCP 9040) -----------------------+------------->+ (Tor Relay)
                               |                 DNSCrypt-Proxy DoH (TCP 9053 via Tor) ----------------------+
                               |  * Blocked:     Drop All Forwarding (Failsafe Isolation)                    |
                               +-----------------------------------------------------------------------------+
```

---

## Dual Topology Operation

PiGuard requires **two distinct physical or wireless network interfaces** with disjoint subnets to prevent routing loops, accidental multi-DHCP collision, or clearnet leaks.

### 1. Home Hotspot Mode (Active)
Configured via [home_hotspot.sh](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/scripts/home_hotspot.sh) and [home.example.json](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tor/home.example.json).

* **Uplink:** Ethernet `eth0` connects directly to the ISP/Home Router LAN (e.g., Jio Router DHCP `192.168.31.x`).
* **Downlink:** Built-in Wi-Fi `wlan0` broadcasts a secured, standalone WPA2 access point (`PiGuard-Home`, `10.78.0.1/24`).
* **Client Addressing:** Downstream devices obtain DHCP addresses in `10.78.0.100`–`10.78.0.199`, with `10.78.0.1` as default gateway and primary DNS.
* **Separation:** ISP Wi-Fi clients remain untouched; only clients connected to `PiGuard-Home` are inspected and routed through the security controls.

### 2. Travel / Public Wi-Fi Mode
Configured via [travel.example.json](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tor/travel.example.json).

* **Uplink:** Wi-Fi `wlan0` associates with external untrusted networks (hotel, campus, public Wi-Fi) as a DHCP client.
* **Downlink:** Ethernet `eth0` operates with static address `10.78.0.1/24`, serving one wired laptop or an external travel AP in bridge mode.
* **Captive Portal Handling:** Supports temporary switching to clearnet `normal` mode for captive-portal authentication before engaging Tor isolation.

### Gateway Traffic Modes

The `piguard-gateway` engine enforces one of three mutually exclusive network states atomically through `nftables`:

| Mode | Downstream Client Internet | Downstream DNS Resolution | Policy & Traffic Handling |
| :--- | :--- | :--- | :--- |
| **`normal`** | Direct IPv4 NAT via uplink interface | Pi-hole DNS ad-blocking and logging enabled | Standard routing. Used during baseline tests or captive portal login. |
| **`tor`** | Downstream TCP redirected to Tor (`10.78.0.1:9040`) | Pi-hole filters queries; upstream DNS queries use DNSCrypt-Proxy DoH (`127.0.0.1:9053`) through Tor | Full privacy isolation. **IPv6, arbitrary UDP, QUIC, and ICMP forwarding are dropped**. |
| **`blocked`** | **Dropped** | **Halted** | Failsafe state. Automatically engaged during service transitions or Tor connection failures to eliminate clearnet leaks. |

---

## Repository Structure

```text
.
├── PiGuard/                          # Hardware commissioning, networking, firewall & broker
│   ├── DEPLOY_DASHBOARD.md           # Step-by-step dashboard deployment & systemd configuration
│   ├── HOME_AND_PUBLIC_WIFI.md       # Operational guide for home hotspot vs travel topology
│   ├── NETWORK_SETUP_GUIDE.md        # Generalized multi-interface network manual
│   ├── README.md                     # Commissioning history and live hardware logs
│   ├── deploy/                       # Systemd unit files and web server configs
│   │   ├── piguard-control.service   # Root broker socket service
│   │   └── piguard-nginx.conf        # Nginx reverse proxy configuration
│   ├── evidence/                     # Audit logs, DNS benchmarks, and network evidence
│   ├── output/                       # Deployment scripts and prepackaged bundle archives
│   ├── scripts/                      # Gateway, broker, and provisioning automation scripts
│   │   ├── check_dns.py              # DNS resolution verification tool
│   │   ├── control_broker.py         # Privileged Unix domain socket broker
│   │   ├── gateway.py                # Core nftables router and mode manager
│   │   ├── home_hotspot.sh           # Safe switcher between travel and home hotspot
│   │   ├── install_dashboard_frontend.sh # Nginx & broker installer
│   │   ├── install_gateway.sh        # Gateway service configuration installer
│   │   ├── install_gateway_deps.sh   # Dependency provisioning script
│   │   ├── install_pihole.sh         # Automated Pi-hole installation wrapper
│   │   ├── install_tailscale_private.sh # Tailscale Serve private access installer
│   │   ├── preflight.sh              # Hardware and OS validation diagnostic
│   │   ├── repair_boot_runtime.sh    # NetworkManager & carrier recovery script
│   │   └── tor_mode.py               # Tor transport connectivity checker
│   ├── tests/                        # Gateway and broker unit/namespace tests
│   │   ├── namespace_gateway.py      # Linux network namespace test runner
│   │   ├── test_control_broker.py    # Control broker command validation tests
│   │   └── test_gateway.py           # nftables rule compilation & state tests
│   └── tor/                          # Tor and DNSCrypt configuration files
│       ├── dnscrypt-proxy.toml       # Pinned Cloudflare DoH via Tor config
│       ├── home.example.json         # Profile: eth0 uplink, wlan0 AP
│       ├── piguard-gateway-guard.service # Early boot firewall guard
│       ├── piguard-gateway-resume.service# Boot state resumption service
│       ├── piguard-tor.service       # Hardened Tor transparent proxy unit
│       ├── piguard-tor-dns.service   # Hardened DNSCrypt-Proxy service unit
│       └── travel.example.json       # Profile: wlan0 uplink, eth0 downlink
│
└── PiGuard_ML/                       # Machine Learning DGA detection & web dashboard
    ├── IMPLEMENTATION_STATUS.md      # Evaluation metrics, resource limits & test logs
    ├── PiGuard_DGA_Training_Colab.ipynb # Training pipeline notebook (Colab ready)
    ├── README.md                     # ML architecture, inference contract & Colab workflow
    ├── data/                         # Public Suffix List, dataset provenance & license
    │   ├── DGA_DATASET_LICENSE.txt   # Dataset licensing terms
    │   ├── README.md                 # Citation & Public Suffix List documentation
    │   ├── domains_features.gz       # Pinned raw dataset
    │   └── public_suffix_list.dat    # ICANN suffix snapshot (2026-10-25)
    ├── deploy/                       # ML background service units
    │   ├── piguard-dashboard.service # Flask dashboard service unit
    │   ├── piguard-observer.service  # DNS query observer service unit
    │   ├── piguard-source-access.path# Pi-hole SQLite ACL watcher path
    │   ├── piguard-source-access.service # Scoped read-only ACL enforcer
    │   └── piguard-source-access.timer   # Periodic ACL refresh timer
    ├── output/                       # Build packages and candidate archives
    ├── piguard/                      # Core application package
    │   ├── accounts.py               # User authentication & role management
    │   ├── benchmark.py              # Hardware resource profiling harness
    │   ├── control.py                # Client connector for control broker socket
    │   ├── dashboard.py              # Flask web UI and REST endpoints
    │   ├── model.py                  # Scorer runtime & integrity validation
    │   ├── network.py                # Network interface inspection utility
    │   ├── observer.py               # Real-time DNS query log monitor
    │   ├── report.py                 # 7-day observation report generator
    │   ├── storage.py                # SQLite state and alert storage engine
    │   ├── templates/                # Jinja2 dashboard UI templates
    │   └── training.py               # CLI tool for model training and evaluation
    ├── piguard_dga_features.py       # Feature Contract v3.0.0 (11 lexical features)
    ├── piguard_dga_inference.py      # Standalone inference CLI with manifest check
    ├── releases/final-001/           # Frozen, validated model release
    │   ├── MANIFEST.sha256           # Cryptographic manifest digest
    │   ├── benchmark-pi-batch500.json# Raspberry Pi benchmark measurements
    │   ├── feature_contract.json     # Feature names, types, and normalization rules
    │   ├── manifest.json             # Artifact SHA-256 integrity map
    │   ├── metrics.json              # Detailed evaluation metrics & slices
    │   ├── piguard_dga_model.joblib  # Serialized Compact Random Forest
    │   └── test_vectors.json         # Reference prediction vectors
    ├── requirements.lock             # Exact locked dependencies (Python 3.13.5)
    ├── test_features.py              # Unit tests for feature extraction
    └── tests/                        # Subsystem test suite (67+ automated tests)
```

---

## Feature Folders Deep Dive

### PiGuard Network Gateway Subsystem

Located in [`PiGuard/`](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard):

* **[deploy/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/deploy)**:
  * [piguard-nginx.conf](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/deploy/piguard-nginx.conf): Terminates TLS locally on `https://10.78.0.1/` using a self-signed certificate. Forwards requests to the Flask dashboard (`127.0.0.1:8080`) and reverses Pi-hole's web admin (`127.0.0.1:8081/admin/`) under the protected path `/pihole/`.
  * [piguard-control.service](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/deploy/piguard-control.service): Systemd daemon running the privileged broker under root with `RuntimeDirectory=piguard-control` and strict umask `0117`.
* **[tor/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tor)**:
  * [piguard-gateway-guard.service](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tor/piguard-gateway-guard.service): Early-boot systemd unit that hooks before `network-pre.target` to establish default drop rules in `nftables` prior to any network interface acquiring IP addresses.
  * [piguard-tor.service](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tor/piguard-tor.service): Sandboxed systemd service for Tor transparent proxying with `MemoryMax=192M`, `ProtectSystem=strict`, and no capabilities beyond binding `TransPort` (TCP 9040).
  * [dnscrypt-proxy.toml](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tor/dnscrypt-proxy.toml): Runs DNSCrypt-Proxy on `127.0.0.1:9053`. Configured with pinned Cloudflare DoH (`cloudflare-doh`), routing queries exclusively over Tor TCP SOCKS (`127.0.0.1:9060`) with remote resolver list downloads disabled.
* **[scripts/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/scripts)**:
  * [gateway.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/scripts/gateway.py): Generates and applies atomic `nftables` rulesets without flushing foreign tables (`flush ruleset` is forbidden; only `inet piguard_gateway` is modified).
  * [control_broker.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/scripts/control_broker.py): Listens on `/run/piguard-control.sock`. Accepts exactly five actions (`status`, `check`, `enable`, `disable`, `block`). Checks hardware status via `/usr/bin/vcgencmd get_throttled` and **refuses to enable Tor if active undervoltage or overheating is detected**.
  * [home_hotspot.sh](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/scripts/home_hotspot.sh): Provides atomic transitions: `prepare` (disables DHCP on eth0, closes UDP 67), `activate` (provisions `PiGuard-Home` AP on wlan0, binds DHCP/DNS), `status`, and `restore`.
* **[tests/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tests)**:
  * [test_gateway.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tests/test_gateway.py) & [test_control_broker.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard/tests/test_control_broker.py): Verifies argument sanitization, CIDR bounds, mode serialization, and broker permission gating.

---

### PiGuard ML Subsystem

Located in [`PiGuard_ML/`](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML):

* **[piguard/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard)**:
  * [observer.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard/observer.py): Runs as an asynchronous polling collector every 15 seconds. Connects to `/etc/pihole/pihole-FTL.db` with `PRAGMA query_only=ON`, reads up to 500 unprocessed records, advances watermarks atomically in `state.db`, and infers DGA probability without blocking DNS queries.
  * [model.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard/model.py): Implements the `Scorer` class. Validates manifest SHA-256 hashes against all release artifacts before calling `joblib.load()`, and compares runtime outputs against pre-computed `test_vectors.json` to verify numerical reproducibility on ARM64.
  * [dashboard.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard/dashboard.py): Flask application offering an alert review queue, interactive gateway controls, and system health statistics. Enforces CSRF tokens on all POST requests, strict HTTP-only cookies, CSV formula-injection escaping (`csv_safe`), and host header filtering (`127.0.0.1` only).
  * [accounts.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard/accounts.py): Provides CLI commands for managing operator accounts with `admin` or `viewer` roles, storing salted cryptographic password hashes.
  * [training.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard/training.py): Orchestrates dataset auditing, 70/15/15 disjoint label partitioning, model training, validation calibration, and frozen candidate generation.
  * [benchmark.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard/benchmark.py): Profiles candidate models on the live Raspberry Pi using single-threaded OpenBLAS (`OPENBLAS_NUM_THREADS=1`) over 20 batches of 500 domains.
* **[releases/final-001/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/releases/final-001)**:
  * The production-deployed, immutable model bundle containing the serialized Compact Random Forest, Public Suffix List snapshot, feature contract, evaluation recipe, and evaluation metrics.
* **[data/](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/data)**:
  * Contains the pinned Public Suffix List ([public_suffix_list.dat](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/data/public_suffix_list.dat)) and the dataset provenance reference ([README.md](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/data/README.md)) citing the academic source (*Wang, Chen & Genc, 2021*).

---

## Machine Learning Pipeline & Metrics

### Feature Contract v3.0.0

Defined in [piguard_dga_features.py](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/piguard_dga_features.py). Operates strictly on the **registrable domain label** (e.g., in `sub.bad-domain.co.uk`, the label scored is `bad-domain`), extracted via the ICANN section of the bundled Public Suffix List:

1. `label_length`: Character length of the registrable label.
2. `entropy`: Shannon entropy computed over label character distribution ($H = -\sum p_i \log_2 p_i$).
3. `digit_ratio`: Proportion of numerical digits (`0-9`) to label length.
4. `alpha_ratio`: Proportion of alphabetic characters (`a-z`) to label length.
5. `hyphen_ratio`: Frequency of hyphens (`-`) relative to length.
6. `vowel_ratio`: Proportion of vowels (`a, e, i, o, u`) relative to alphabetic count.
7. `unique_char_ratio`: Cardinality of unique characters divided by length.
8. `max_consonant_run`: Length of the longest contiguous sequence of consonants.
9. `max_digit_run`: Length of the longest contiguous sequence of digits.
10. `hex_char_ratio`: Ratio of hexadecimal characters (`0-9, a-f`) to label length.
11. `has_punycode`: Boolean flag identifying IDN punycode prefixes (`xn--`).

### Resource Budgets & Model Selection

Candidates were evaluated under strict hardware performance policies on the Raspberry Pi 3B+ (ARM64):
* **Memory Policy:** Peak Scorer RSS $\le$ 256 MiB.
* **Latency Policy:** p95 inference time $\le$ 2,000 ms for an uncached warm batch of 500 domain labels.

| Candidate Model | Peak Scorer RSS | Warm Batch-500 p95 Latency | Status & Selection Outcome |
| :--- | :--- | :--- | :--- |
| **Baseline Random Forest** | > 380 MiB | ~ 2,450 ms | **Rejected** (Exceeded memory limit on 1 GB Pi) |
| **Logistic Regression** | ~ 92 MiB | ~ 410 ms | **Rejected** (Lower recall on complex DGA structures) |
| **Compact Random Forest** | **178.40 MiB** | **1,205.57 ms** | **Accepted & Promoted to `final-001`** |

### Held-Out Evaluation Results

The frozen `final-001` release was evaluated once against the locked, held-out test split (13,683 public samples, completely disjoint from training labels).

Operating threshold was locked at **0.8914** (maximizing validation recall under a strict False Positive Rate budget $\le$ 1.0%):

| Metric | Measured Value | 95% Confidence Interval |
| :--- | :--- | :--- |
| **Test Samples ($N$)** | 13,683 rows | — |
| **Precision** | **98.87%** | — |
| **Recall** | **56.81%** | [55.68%, 57.94%] |
| **False Positive Rate (FPR)** | **0.76%** | [0.57%, 1.01%] |
| **F1 Score** | **0.7216** | — |
| **ROC-AUC** | **0.9197** | — |
| **PR-AUC (Average Precision)** | **0.9420** | — |

> [!NOTE]
> PiGuard ML operates in an **alert-only** posture. A high DGA score flags the domain for operator triage on the dashboard review queue; it does not inject blocking rules into Pi-hole or terminate connections.

---

## Security & Isolation Architecture

```text
[ Unauthenticated Users ]
           |
           x  (Uplink: All management ports dropped by nftables)
           |
[ Protected LAN Clients ]
           |
           +---> TCP 443 (HTTPS) ---> Nginx (TLS Termination)
           |                              |
           |                              v (Proxy to 127.0.0.1:8080)
           |                      [ Flask Dashboard (User: piguard) ]
           |                      - Strict Session Cookies (SameSite=Strict)
           |                      - Anti-CSRF Validation on POSTs
           |                      - CSV Formula Sanitization
           |                      - NO SUDO PRIVILEGES
           |                              |
           |                              v Unix Domain Socket (/run/piguard-control.sock)
           |                      [ Root Broker (control_broker.py) ]
           |                      - Validates caller UID/GID
           |                      - Checks hardware throttling (vcgencmd)
           |                      - Whitelists 5 fixed commands only
           |                              |
           |                              v Execv (/usr/local/bin/piguard-gateway)
           |                      [ nftables Kernel Table (inet piguard_gateway) ]
```

1. **Least-Privilege Execution:** The Flask dashboard runs under the unprivileged `piguard` system user and possesses no entry in `/etc/sudoers`.
2. **Fixed-Action Root Broker:** Privileged network operations occur exclusively through a Unix domain socket (`/run/piguard-control.sock`). The broker executes only 5 hard-coded actions (`status`, `check`, `enable`, `disable`, `block`) and sanitizes all inputs.
3. **Hardware-Guarded Protection:** The broker queries Raspberry Pi hardware telemetry via `vcgencmd get_throttled`. If the Pi is experiencing active undervoltage (`0x50005` or similar), enabling Tor is blocked to prevent kernel hangs or filesystem corruption.
4. **Scoped Read-Only Database Access:** The ML observer is not granted membership in the `pihole` system group. Access to `/etc/pihole/pihole-FTL.db` is maintained using dedicated POSIX filesystem ACLs managed by a scoped systemd timer ([piguard-source-access](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/deploy/piguard-source-access.service)).
5. **Cryptographic Release Verification:** The `Scorer` verifies the complete SHA-256 manifest of the release bundle before deserializing any joblib object, safeguarding against tampering or pickled arbitrary code execution.
6. **Zero External Surface:** In travel and public modes, the public-facing uplink interface rejects all inbound connection attempts to Pi-hole, the dashboard, or SSH. Remote access is permitted only through private [Tailscale](https://tailscale.com) tunnels authenticated with MagicDNS.

---

## Deployment & Verification Workflow

### 1. Hardware Prerequisites
* Raspberry Pi 3B+ (64-bit ARMv8 Cortex-A53).
* 32 GB or 64 GB Class 10 MicroSD card (Debian 12 Bookworm / Raspberry Pi OS 64-bit).
* Official Raspberry Pi 5.1V 2.5A power supply (prevents undervoltage throttling).
* Dedicated Ethernet cable for client link or uplink connectivity.

### 2. Gateway & Dashboard Installation

On the Raspberry Pi terminal:

```bash
# 1. Clone or sync workspace to the Pi home directory
scp -r PiGuard PiGuard_ML krat0s@KREO.local:~/

# 2. Run hardware preflight diagnostics
cd ~/PiGuard
bash scripts/preflight.sh

# 3. Install and configure Pi-hole Core & FTL
bash scripts/install_pihole.sh

# 4. Install gateway dependencies and persistent firewall guard
sudo bash scripts/install_gateway_deps.sh
sudo bash scripts/install_gateway.sh tor/home.example.json

# 5. Install Nginx reverse proxy and privileged control broker
sudo bash scripts/install_dashboard_frontend.sh
```

### 3. Machine Learning Observer Activation

```bash
cd ~/PiGuard_ML

# 1. Create virtual environment and install locked dependencies
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock

# 2. Run validation test suite
.venv/bin/pytest test_features.py tests -q

# 3. Activate the evaluated final-001 release
sudo bash scripts/activate_final.sh

# 4. Create administrative dashboard accounts
sudo -u piguard env PYTHONPATH=/opt/piguard/current /opt/piguard/current/.venv/bin/python \
  -m piguard.accounts --state /var/lib/piguard/state.db --username admin --role admin
```

### 4. Client Verification Checklist

From a protected downstream laptop (Wi-Fi or wired Ethernet):

1. **Verify DHCP & Routes:**
   ```bash
   # Confirm IP is 10.78.0.x and Default Gateway / DNS is 10.78.0.1
   ip route show default
   ```
2. **Verify DNS Filtering:**
   ```bash
   # Should resolve to 0.0.0.0 (Pi-hole blocking)
   dig @10.78.0.1 doubleclick.net A +short
   ```
3. **Verify Clearnet Routing (Normal Mode):**
   ```bash
   curl -4 https://check.torproject.org/api/ip
   # Expected response: {"IsTor": false}
   ```
4. **Enable Tor via Dashboard (`https://10.78.0.1/gateway`) and Verify Privacy Path:**
   ```bash
   curl -4 https://check.torproject.org/api/ip
   # Expected response: {"IsTor": true}
   ```
5. **Verify Leak Prevention:**
   ```bash
   # External DNS probes directed to 1.1.1.1 should be intercepted by Pi-hole
   dig @1.1.1.1 doubleclick.net A +short
   # Should return 0.0.0.0
   ```

---

## Troubleshooting & Recovery

* **Thermal & Undervoltage Warning:**
  Check live throttling flags:
  ```bash
  vcgencmd get_throttled
  ```
  If output is `0x50005`, an undervoltage condition is active. Replace the power supply or micro-USB cable. The control broker will refuse Tor transitions until cleared.

* **Reverting to Clearnet / Emergency Fallback:**
  If Tor transitions fail or the network stalls, restore normal NAT routing from the Pi terminal:
  ```bash
  sudo /usr/local/bin/piguard-gateway disable
  ```

* **Captive Portal Login on Public Wi-Fi:**
  1. Open the dashboard at `https://10.78.0.1/` and click **Restore normal routing**.
  2. Connect the Pi uplink to the public SSID using `sudo nmtui`.
  3. Navigate to `http://neverssl.com` from a downstream client or use a browser directly on the Pi to satisfy the captive portal.
  4. Once Internet connectivity is confirmed, return to the dashboard and re-enable **Tor Mode**.

* **Reviewing System Logs:**
  ```bash
  # Check ML Observer logs
  journalctl -u piguard-observer -n 50 --no-pager

  # Check Gateway & Tor units
  journalctl -u piguard-gateway-guard -u piguard-tor -u piguard-tor-dns --since "15 minutes ago"
  ```

---

## License & Provenance

* **Software:** MIT License.
* **DGA Dataset Provenance:** Curated from Wang, Chen & Genc (2021), *A Dictionary-Based Method for Detecting Machine-Generated Domains*, DOI: 10.1080/19393555.2020.1834650. See [DGA_DATASET_LICENSE.txt](file:///Users/kratos_2004/Downloads/Major%20Proj/GitFol/PiGuard_ML/data/DGA_DATASET_LICENSE.txt).
* **Public Suffix List:** Mozilla Public License 2.0 (MPL-2.0). Bundled snapshot pinned at commit `b9c75bc92d16736875f094b05180befb163d756a`.
