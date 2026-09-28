# LLAMA RPC NODES v1.0.0

## Bahasa Indonesia

Rilis Windows portabel pertama. Satu `LLAMA-RPC.exe` dapat dijalankan sebagai SERVER utama atau NODE pembantu; `CHECK.exe` bersifat opsional dan cukup dijalankan pada satu PC pemeriksa. Model GGUF tidak disertakan.

Perubahan penting:

- Endpoint Cline lokal `http://127.0.0.1:1235/v1` membersihkan label nomor baris tampilan seperti `93 |` dari konteks baca dan memberi panduan agar model tidak menyalinnya ke patch. API biasa tetap di `http://127.0.0.1:1234/v1`.
- Perbaikan dikemas ke dalam EXE tunggal; PC tujuan tidak perlu memasang Python.
- Dokumentasi dua bahasa dan petunjuk Cline diperbarui. Tools, MCP, rules, dan skills tetap dijalankan oleh Cline.

Unduh `LLAMA-RPC.exe` untuk PC utama dan semua node. Unduh `CHECK.exe` hanya bila ingin memeriksa koneksi dan kemampuan cluster. Cocokkan SHA-256 dengan `SHA256SUMS.txt` sebelum menjalankan file. Gunakan RPC hanya pada LAN tepercaya; jangan buka port node `50052` ke internet.

Verifikasi: 5 unit test lulus; uji edit Cline dengan GPT-OSS 20B menghasilkan patch tanpa nomor baris dan file Python valid; EXE baru lulus pemeriksaan arsip dan startup `--help` mode SERVER/NODE. Pemuatan GGUF penuh dari EXE rilis belum diuji. Pengaman Cline bersifat *best effort*: tetap periksa diff hasil edit.

## English

First portable Windows release. The same `LLAMA-RPC.exe` runs as the main SERVER or a helper NODE. `CHECK.exe` is optional and only needs to run on one checking PC. GGUF model files are not included.

Highlights:

- The localhost Cline endpoint `http://127.0.0.1:1235/v1` removes display-only line labels such as `93 |` from read context and guides the model not to copy them into patches. The ordinary API remains at `http://127.0.0.1:1234/v1`.
- The fix is bundled in the single EXE; target PCs do not need Python.
- Bilingual documentation and Cline setup instructions are updated. Cline still runs tools, MCP, rules, and skills.

Download `LLAMA-RPC.exe` for the main PC and all nodes. Download `CHECK.exe` only if you want to inspect cluster connectivity and capacity. Verify SHA-256 against `SHA256SUMS.txt` before running. Use RPC only on a trusted LAN; never expose node port `50052` to the internet.

Verification: 5 unit tests passed; a GPT-OSS 20B Cline edit produced a patch without line labels and valid Python; the new EXE passed archive inspection and SERVER/NODE `--help` startup checks. A full GGUF load from the release EXE has not yet been tested. The Cline guard is best-effort: always review edited diffs.

## SHA-256

```text
6D3EBBF987D0204044656427FC77FB22E9762A57B098DD1BC1232CD7A86F0F75  LLAMA-RPC.exe
B52FD3823F955CD4E866EAC36BF81FD66607CEE21712746181CD030DBD7F776C  CHECK.exe
```
