# LLAMA RPC NODES v1.0.1

## Bahasa Indonesia

Perbaikan tampilan alamat Cline pada SERVER. Satu `LLAMA-RPC.exe` tetap menjalankan mode SERVER maupun NODE; `CHECK.exe` tetap opsional.

- Ringkasan startup sekarang menampilkan **Cline aman (DISARANKAN): `http://127.0.0.1:1235/v1`** sebelum pesan “Tekan Ctrl+C”, bila pengaman berhasil aktif.
- Jika pengaman gagal aktif atau sengaja dimatikan dengan `--no-cline-guard`, alamat `1234` diberi label **Cline tanpa pengaman** dan penyebabnya ditampilkan. Tidak ada lagi baris “Cline langsung” yang mudah disalahartikan sebagai alamat yang disarankan.
- Pengaturan model, GPU, RPC NODE, serta `CHECK.exe` tidak diubah.

Unduh `LLAMA-RPC.exe` yang sama untuk PC utama dan semua node. Gunakan Model ID yang ditampilkan SERVER. Cline tetap menjalankan tools, MCP, rules, dan skills. Model GGUF tidak disertakan. Cocokkan file dengan `SHA256SUMS.txt` sebelum menjalankan. Periksa diff hasil edit AI karena pengaman nomor baris bersifat *best effort*.

Verifikasi: 8 unit test lulus; arsip EXE terbaca; startup `--help` mode SERVER dan NODE lulus. Pemuatan GGUF penuh dari EXE v1.0.1 belum diuji. Proses SERVER yang sudah berjalan harus dihentikan lalu dijalankan ulang agar tampilan baru muncul.

## English

SERVER display fix for the Cline endpoint. The same single `LLAMA-RPC.exe` still runs both SERVER and NODE modes; `CHECK.exe` remains optional.

- The startup summary now shows **Cline aman (DISARANKAN): `http://127.0.0.1:1235/v1`** before “Tekan Ctrl+C” when the guard starts successfully.
- If the guard fails or is disabled with `--no-cline-guard`, port `1234` is clearly labeled **Cline tanpa pengaman** with an explanatory message. The ambiguous “Cline langsung” line is gone.
- Model, GPU, RPC NODE, and `CHECK.exe` behavior is unchanged.

Download the same `LLAMA-RPC.exe` for the main PC and all nodes. Use the Model ID shown by SERVER. Cline still runs tools, MCP, rules, and skills. GGUF models are not included. Verify files against `SHA256SUMS.txt` before running. Review AI edits because the line-number guard is best-effort.

Verification: 8 unit tests passed; the EXE archive was readable; SERVER and NODE `--help` startup checks passed. A full GGUF load from the v1.0.1 EXE has not yet been tested. An already-running SERVER must be stopped and restarted to show the new display.

## SHA-256

```text
2F6301AACE8EECB919DA7603477029C9C1D58117780BD161C5CB9F77A0C405CB  LLAMA-RPC.exe
B52FD3823F955CD4E866EAC36BF81FD66607CEE21712746181CD030DBD7F776C  CHECK.exe
```
