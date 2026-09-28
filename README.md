# LLAMA RPC NODES

[Bahasa Indonesia](#bahasa-indonesia) · [English](#english)

Jalankan satu model GGUF pada PC utama dengan bantuan GPU dari beberapa PC pembantu melalui jaringan lokal. Aplikasi Windows ini membungkus `llama.cpp` RPC: PC utama menyediakan API yang kompatibel dengan OpenAI, sedangkan node menyediakan perangkat komputasi. Internet tidak diperlukan saat cluster berjalan di LAN.

![Topologi LLAMA RPC NODES: PC pembantu terhubung melalui switch ke PC utama](CLUSTER%20NODE.png)

_Ilustrasi: router pada gambar bersifat opsional jika IP diatur manual atau DHCP lokal tersedia. Label “Cat 8” hanya contoh kabel; gunakan kabel sesuai kecepatan dan jarak LAN._

## Bahasa Indonesia

### Fitur utama

- **Satu `LLAMA-RPC.exe`, dua mode:** SERVER utama atau NODE pembantu. EXE membundel Python dan runtime; PC pengguna tidak perlu memasang Python.
- **Banyak node:** tambah, hapus, dan pilih node untuk setiap sesi. Daftar disimpan di `server-nodes.json` di samping EXE; saat pertama digunakan, daftar kosong.
- **Backend otomatis:** mencoba CUDA untuk NVIDIA yang kompatibel, lalu Vulkan, kemudian CPU.
- **Pemilihan model:** masukkan folder model; SERVER mencari `.gguf` di semua subfolder. File model hanya diperlukan pada PC utama.
- **Pengaturan inferensi:** pilih panjang konteks dan Think/Reasoning (`auto`, `on`, `off`). Menu lanjutan menyediakan sampling, output, memori, dan performa.
- **API lokal:** `http://127.0.0.1:1234/v1` untuk klien biasa. Endpoint khusus Cline di `http://127.0.0.1:1235/v1` membersihkan label nomor baris berurutan dari konteks baca sebelum diteruskan ke model.
- **`CHECK.exe`:** jalankan hanya pada satu PC pemeriksa untuk melihat node online, VRAM, latensi/jitter RPC, dan GPU PC pemeriksa.

### Kebutuhan

- Windows 10/11 64-bit pada PC utama dan node, dengan driver GPU yang sesuai.
- LAN yang memungkinkan PC utama menjangkau TCP `50052` di setiap node. Gunakan switch untuk banyak node. Internet/router tidak wajib, tetapi IP dan rute jaringan harus benar.
- Ruang kosong beberapa GB di TEMP untuk ekstraksi EXE satu berkas, serta RAM/VRAM yang cukup untuk model GGUF dan konteks yang dipilih.
- Model GGUF *instruction/chat* untuk percakapan atau Cline. Keandalan `tool_calls` bergantung pada kemampuan model dan template chat-nya.

### Mulai cepat

1. Unduh `LLAMA-RPC.exe` dari [GitHub Releases](https://github.com/anonimusman00-02/LLAMA-RPC-NODES/releases/latest). Salin EXE yang sama ke PC utama dan semua PC pembantu. `CHECK.exe` hanya dibutuhkan pada PC pemeriksa.
2. Pada setiap PC pembantu, jalankan `LLAMA-RPC.exe` dan pilih **2. NODE pembantu**. Jika aturan firewall TCP `50052` belum berhasil dibuat, jalankan sekali sebagai Administrator. Biarkan jendela node terbuka dan catat IP:port yang tampil.
3. Pada PC utama, jalankan EXE yang sama dan pilih **1. SERVER utama**. Pilih **2. Tambah Node** untuk setiap alamat pembantu; **3. Hapus Node** untuk alamat yang tidak digunakan.
4. Pilih **1. Mulai**. Masukkan folder model (misalnya `D:\Models`), pilih model GGUF dan perangkat yang digunakan, lalu tentukan konteks dan mode Think. Tekan Enter pada pengaturan lanjutan untuk menerima default.
5. Tunggu hingga log `model loaded` dan alamat API tampil. Progres `~99%` adalah perkiraan aktivitas disk/RAM; alokasi GPU/RPC masih dapat berlanjut setelah itu.
6. Arahkan aplikasi klien biasa ke `http://127.0.0.1:1234/v1`, atau Cline ke `http://127.0.0.1:1235/v1`.

Contoh perintah tanpa menu:

```powershell
# Pada PC pembantu
.\LLAMA-RPC.exe --mode node

# Pada PC utama: folder model dan satu node contoh
.\LLAMA-RPC.exe --mode server "D:\Models" --node 192.168.1.20:50052 --ctx-size 8192 --think auto

# Periksa cluster dari satu PC saja
.\CHECK.exe --node 192.168.1.20:50052
```

Repositori menyediakan `server-nodes.example.json`. Konfigurasi nyata di `release/server-nodes.json` berisi IP lokal Anda dan tidak masuk commit publik.

### Cline dan nilai default

Di Cline, pilih **OpenAI Compatible**, isi Base URL `http://127.0.0.1:1235/v1`, dan salin **Model ID** dari tampilan SERVER. Jika formulir mewajibkan API key, isi nilai dummy seperti `local`. Samakan context window Cline dengan konteks efektif di SERVER. Tools, MCP, rules, dan skills tetap dijalankan Cline; SERVER hanya menyajikan respons dan `tool_calls` model. Endpoint aman ini hanya tersedia di PC utama dan dapat dimatikan dengan `--no-cline-guard`. Ia mengurangi risiko model menyalin label seperti `92 |` dari hasil baca file; ia tidak memvalidasi atau memperbaiki patch hasil model, jadi tetap periksa diff sebelum menerima edit.

Saat SERVER dimulai, gunakan baris **Cline aman (DISARANKAN)** yang tampil sebelum instruksi Ctrl+C. Jika pengaman gagal aktif atau dinonaktifkan, aplikasi menampilkan **Cline tanpa pengaman** untuk port `1234` disertai peringatan.

| Pengaturan | Default |
| --- | --- |
| Konteks interaktif | 2.048 token; dapat diubah saat mulai |
| Think/Reasoning | `auto` |
| Temperature / Top-K / Top-P / Min-P | `0.8` / `40` / `0.95` / `0.05` |
| Repeat penalty | `1.0` |
| GPU layers / Fit | `auto` / `on` |
| Flash Attention / KV cache | `on` / `F16` |
| Batch / micro-batch / slot paralel | `512` / `512` / `1` |
| Prompt cache / continuous batching | `on` / `on` |
| Batas output SERVER | Tidak dibatasi (`-1`); klien dapat menetapkan batas |

Menu lanjutan dapat mengubah sampling, output, reasoning budget, cache, thread, dan alokasi GPU. Parameter permintaan dari klien dapat menimpa sebagian default. Konteks besar memakai lebih banyak RAM/VRAM dan dapat memperlama load.

### Pemeriksaan dan masalah umum

- **Node tidak terdeteksi:** pastikan NODE masih berjalan, alamat/port benar, dan firewall mengizinkan TCP `50052`. Dari PC utama jalankan `Test-NetConnection 192.168.1.20 -Port 50052`.
- **Load tertahan di `~99%`:** tunggu `model loaded` atau cek `http://127.0.0.1:1234/health`. HTTP `503` berarti pemuatan belum selesai. Kurangi konteks atau jumlah node bila RAM/VRAM hampir habis.
- **Inferensi lambat:** lebih banyak node tidak selalu lebih cepat. Pakai LAN kabel berlatensi rendah dan bandingkan token/detik dengan hanya node yang dibutuhkan untuk memuat model.
- **Cline error konteks/JSON tool:** periksa konteks efektif dan kemampuan tool calling model. Default SERVER memakai satu slot paralel sehingga konteks tidak terbagi.
- **CHECK tidak menampilkan MB/s:** CHECK mengukur respons dan kestabilan RPC, bukan bandwidth transfer besar. NODE tidak perlu menjalankan CHECK.

### Keamanan dan publikasi

RPC `llama.cpp` masih eksperimental dan tidak menyediakan autentikasi node bawaan. Gunakan hanya pada LAN tepercaya; jangan buka TCP `50052` ke internet. API SERVER mendengarkan `127.0.0.1` secara default.

Git melacak pembungkus Python, spesifikasi build, dokumen, dan gambar. Runtime vendor, arsip besar, EXE, model, serta konfigurasi IP nyata dikecualikan dari commit. `LLAMA-RPC.exe` sekitar 1 GB, sehingga distribusikan sebagai **asset GitHub Release**. Berkas lokal di `release/` tetap ada. Untuk membangun dari sumber, spesifikasi PyInstaller yang ada merujuk ke `D:\LLAMA RPC` dan memerlukan runtime `llama.cpp` yang cocok.

**Publikasi lewat GitHub Desktop:** buka folder `LLAMA RPC NODES` sebagai repositori, periksa daftar perubahan, commit kode/dokumen/gambar, lalu pilih **Publish repository**. Sesudah repositori tersedia di GitHub, buka halaman **Releases → Draft a new release** dan unggah `release/LLAMA-RPC.exe`, `release/CHECK.exe`, serta `release/SHA256SUMS.txt` sebagai asset. Jangan seret seluruh folder `release/` ke commit Git. [GitHub membatasi berkas Git biasa hingga 100 MiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) dan [asset Release harus di bawah 2 GiB per berkas](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

Proyek memakai [llama.cpp](https://github.com/ggml-org/llama.cpp). Ikuti lisensi komponen upstream dan model GGUF yang Anda gunakan. Lisensi untuk kode pembungkus proyek ini belum ditetapkan di repositori.

---

## English

Run one GGUF model on a main PC with help from other GPUs over a local network. This Windows application wraps `llama.cpp` RPC: the main PC exposes an OpenAI-compatible API, while helper nodes provide compute devices. The local cluster needs no Internet connection.

![LLAMA RPC NODES topology: helper PCs connect through a switch to the main PC](CLUSTER%20NODE.png)

_Illustration: the router is optional if IP addresses are configured manually or local DHCP is available. “Cat 8” cable labels are examples; choose cabling for your network speed and distance._

### Features

- **One `LLAMA-RPC.exe`, two modes:** main SERVER or helper NODE. The EXE bundles Python and the runtime; target PCs do not need a separate Python installation.
- **Multiple nodes:** add, remove, and select nodes per session. Addresses are stored in `server-nodes.json` beside the EXE; the initial list is empty.
- **Automatic backend:** tries compatible NVIDIA CUDA, then Vulkan, then CPU.
- **Model discovery:** enter a model directory; SERVER scans subfolders for `.gguf` files. Only the main PC needs the model file.
- **Inference controls:** select context length and Think/Reasoning (`auto`, `on`, `off`). Optional advanced menus cover sampling, output, memory, and performance.
- **Local API:** `http://127.0.0.1:1234/v1` for ordinary clients. The dedicated Cline endpoint at `http://127.0.0.1:1235/v1` removes consecutive display-only line labels from read context before forwarding it to the model.
- **`CHECK.exe`:** run on one checking PC to inspect online nodes, VRAM, RPC latency/jitter, and the checking PC's GPU.

### Requirements

- 64-bit Windows 10/11 on the main PC and nodes, with suitable GPU drivers.
- A LAN route from the main PC to TCP `50052` on every node. Use a switch for multiple nodes. A router/Internet connection is optional, but IP addressing and routing must work.
- Several GB of free TEMP space for one-file EXE extraction, plus enough RAM/VRAM for the GGUF model and chosen context.
- An instruction/chat GGUF model for conversation or Cline. Reliable `tool_calls` depend on the model and its chat template.

### Quick start

1. Download `LLAMA-RPC.exe` from [GitHub Releases](https://github.com/anonimusman00-02/LLAMA-RPC-NODES/releases/latest). Copy the same EXE to the main PC and every helper PC. Only the checking PC needs `CHECK.exe`.
2. On each helper PC, launch `LLAMA-RPC.exe`, choose **2. NODE pembantu**, and leave its window open. Run it once as Administrator if the TCP `50052` firewall rule could not be created. Note its displayed IP:port.
3. On the main PC, launch the same EXE and choose **1. SERVER utama**. Choose **2. Tambah Node** for each helper address; use **3. Hapus Node** to remove an address.
4. Choose **1. Mulai**. Enter a model directory such as `D:\Models`, select a GGUF model and compute devices, then set context and Think mode. Press Enter at the advanced-settings question to keep defaults.
5. Wait for `model loaded` and the API address. `~99%` estimates disk/RAM activity; GPU/RPC allocation may continue afterward.
6. Point an ordinary client to `http://127.0.0.1:1234/v1`, or Cline to `http://127.0.0.1:1235/v1`.

Command-line example:

```powershell
# Helper PC
.\LLAMA-RPC.exe --mode node

# Main PC: example model directory and helper address
.\LLAMA-RPC.exe --mode server "D:\Models" --node 192.168.1.20:50052 --ctx-size 8192 --think auto

# Check the cluster from one PC
.\CHECK.exe --node 192.168.1.20:50052
```

The repository includes `server-nodes.example.json`. Your real `release/server-nodes.json` contains local IP addresses and is excluded from public commits.

### Cline and defaults

In Cline, select **OpenAI Compatible**, set Base URL to `http://127.0.0.1:1235/v1`, and copy the **Model ID** shown by SERVER. If the UI requires an API key, use a dummy value such as `local`. Match Cline's context window to the effective SERVER context. Cline owns tools, MCP, rules, and skills; SERVER returns model responses and structured `tool_calls`. This localhost-only endpoint can be disabled with `--no-cline-guard`. It reduces the chance of copying display labels such as `92 |` from file-read results; it does not validate or repair generated patches, so review diffs before accepting edits.

At SERVER startup, use the **Cline aman (DISARANKAN)** line shown before the Ctrl+C instruction. If the guard cannot start or is disabled, the app explicitly labels port `1234` as **Cline tanpa pengaman** and shows a warning.

| Setting | Default |
| --- | --- |
| Interactive context | 2,048 tokens; adjustable at startup |
| Think/Reasoning | `auto` |
| Temperature / Top-K / Top-P / Min-P | `0.8` / `40` / `0.95` / `0.05` |
| Repeat penalty | `1.0` |
| GPU layers / Fit | `auto` / `on` |
| Flash Attention / KV cache | `on` / `F16` |
| Batch / micro-batch / parallel slots | `512` / `512` / `1` |
| Prompt cache / continuous batching | `on` / `on` |
| SERVER output limit | Unlimited (`-1`); clients may set a limit |

Advanced menus can change sampling, output limits, reasoning budget, caching, threads, and GPU allocation. Client requests can override some defaults. Large contexts require more RAM/VRAM and can increase model-load time.

### Checks and troubleshooting

- **Node missing:** keep NODE running, verify its address/port and firewall allowance for TCP `50052`. From the main PC run `Test-NetConnection 192.168.1.20 -Port 50052`.
- **Load stays at `~99%`:** wait for `model loaded` or check `http://127.0.0.1:1234/health`. HTTP `503` means loading is unfinished. Reduce context or node count if RAM/VRAM is almost full.
- **Slow inference:** more nodes do not always improve speed. Use a low-latency wired LAN and compare token throughput using only nodes needed to fit the model.
- **Cline context/tool JSON errors:** check the effective context and the model's tool-calling ability. SERVER defaults to one parallel slot so the context is not split.
- **No MB/s number in CHECK:** CHECK measures RPC responsiveness and connection stability, not bulk transfer bandwidth. Nodes do not need CHECK.

### Security and publication

`llama.cpp` RPC is experimental and has no built-in node authentication. Use it only on a trusted LAN; do not expose TCP `50052` to the Internet. By default, the main API listens only on `127.0.0.1`.

Git tracks the Python wrappers, build specifications, documentation, and image. Vendor runtimes, large archives, EXEs, models, and real IP configuration are excluded from commits. `LLAMA-RPC.exe` is about 1 GB, so distribute it as a **GitHub Release asset**. Local `release/` files remain in place. The existing PyInstaller specifications refer to `D:\LLAMA RPC` and require a matching `llama.cpp` runtime for source builds.

**Publish with GitHub Desktop:** add the `LLAMA RPC NODES` folder as a repository, review the changed-file list, commit the source/docs/image, and select **Publish repository**. On GitHub, open **Releases → Draft a new release** and attach `release/LLAMA-RPC.exe`, `release/CHECK.exe`, and `release/SHA256SUMS.txt` as assets. Do not add the entire local `release/` folder to the Git commit. [Regular Git files are limited to 100 MiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github), while [each Release asset must be under 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

This project uses [llama.cpp](https://github.com/ggml-org/llama.cpp). Follow upstream component and GGUF model licenses. No license for this project's wrapper code has been declared in the repository.
