#!/usr/bin/env python3
"""Interface gráfica moderna para transcrição de reuniões e geração de atas."""
from __future__ import annotations
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from datetime import datetime
from tkinter import scrolledtext
from tkinter import filedialog, messagebox, ttk
from typing import Optional
from meeting_transcriber import MeetingTranscriptResult, transcribe_meeting
class TranscriptionApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Ata AI — Transcrição de Reuniões")
        self.root.geometry("1100x780")
        self.root.minsize(980, 700)
        self.root.configure(bg="#f3f6fb")
        self.output_dir = Path("./transcricoes")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.queue: list[dict] = []
        self.completed_results: list[MeetingTranscriptResult] = []
        self.failed_items: list[str] = []
        self.is_processing = False
        self.worker_thread: Optional[threading.Thread] = None
        self.last_directory = Path.home()
        self.current_log_file: Optional[Path] = None
        self.colors = {
            "bg": "#f3f6fb",
            "card": "#ffffff",
            "border": "#dbe4f0",
            "text": "#172033",
            "muted": "#63708a",
            "primary": "#2563eb",
            "primary_hover": "#1d4ed8",
            "success": "#059669",
            "success_hover": "#047857",
            "danger": "#dc2626",
            "danger_hover": "#b91c1c",
            "accent": "#7c3aed",
        }
        self._configure_style()
        self._build_ui()
        self._refresh_queue_view()
        self._update_progress(0, "Aguardando seleção de arquivos", "Selecione um ou mais arquivos para começar.")
    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["card"], relief="flat")
        style.configure("Header.TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 24, "bold"))
        style.configure("SubHeader.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 10))
        style.configure("Section.TLabel", background=self.colors["card"], foreground=self.colors["text"], font=("Segoe UI", 12, "bold"))
        style.configure("Hint.TLabel", background=self.colors["card"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=self.colors["card"], foreground=self.colors["muted"], font=("Segoe UI", 10))
        style.configure("BigStatus.TLabel", background=self.colors["card"], foreground=self.colors["text"], font=("Segoe UI", 11, "bold"))
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(16, 10),
            background=self.colors["primary"],
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            focuscolor=self.colors["primary"],
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.colors["primary_hover"]), ("disabled", "#a9b8d5")],
            foreground=[("disabled", "#edf2f7")],
        )
        style.configure(
            "Success.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(16, 10),
            background=self.colors["success"],
            foreground="white",
            borderwidth=0,
        )
        style.map(
            "Success.TButton",
            background=[("active", self.colors["success_hover"]), ("disabled", "#a9b8d5")],
        )
        style.configure(
            "Danger.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 10),
            background=self.colors["danger"],
            foreground="white",
            borderwidth=0,
        )
        style.map(
            "Danger.TButton",
            background=[("active", self.colors["danger_hover"]), ("disabled", "#a9b8d5")],
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(16, 10),
            background=self.colors["accent"],
            foreground="white",
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#6d28d9"), ("disabled", "#a9b8d5")],
        )
        style.configure(
            "Queue.Treeview",
            background="white",
            fieldbackground="white",
            foreground=self.colors["text"],
            rowheight=32,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Queue.Treeview.Heading",
            font=("Segoe UI", 10, "bold"),
            background="#eff4fb",
            foreground=self.colors["text"],
            padding=(8, 8),
        )
        style.map("Queue.Treeview", background=[("selected", "#dbeafe")])
        style.configure(
            "Modern.Horizontal.TProgressbar",
            troughcolor="#e7eef8",
            background=self.colors["primary"],
            bordercolor="#e7eef8",
            lightcolor=self.colors["primary"],
            darkcolor=self.colors["primary"],
            thickness=18,
        )
    def _build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, style="App.TFrame", padding=24)
        root_frame.pack(fill=tk.BOTH, expand=True)
        header = ttk.Frame(root_frame, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 18))
        ttk.Label(header, text="Ata AI", style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Transcrição com suporte a OGG, fila múltipla, progresso real e ata com tópicos e falantes estimados.",
            style="SubHeader.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))
        card = tk.Frame(root_frame, bg=self.colors["card"], highlightbackground=self.colors["border"], highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True)
        card_inner = ttk.Frame(card, style="Card.TFrame", padding=22)
        card_inner.pack(fill=tk.BOTH, expand=True)
        controls = ttk.Frame(card_inner, style="Card.TFrame")
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Selecionar arquivos", style="Primary.TButton", command=self.select_files).pack(side=tk.LEFT)
        ttk.Button(controls, text="Iniciar transcrição", style="Success.TButton", command=self.start_transcription).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="Limpar fila", style="Danger.TButton", command=self.clear_queue).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(
            card_inner,
            text="Formatos aceitos: MP4, MKV, MOV, AVI, WEBM, OGG, OGA, OPUS, M4A, MP3, WAV e AAC.",
            style="Hint.TLabel",
        ).pack(anchor=tk.W, pady=(10, 14))
        queue_section = ttk.Frame(card_inner, style="Card.TFrame")
        queue_section.pack(fill=tk.BOTH, expand=True)
        ttk.Label(queue_section, text="Fila de transcrição", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 8))
        tree_container = tk.Frame(queue_section, bg=self.colors["card"], highlightbackground=self.colors["border"], highlightthickness=1)
        tree_container.pack(fill=tk.BOTH, expand=True)
        columns = ("arquivo", "status")
        self.queue_tree = ttk.Treeview(tree_container, columns=columns, show="headings", style="Queue.Treeview", selectmode="browse")
        self.queue_tree.heading("arquivo", text="Arquivo")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.column("arquivo", width=680, anchor=tk.W)
        self.queue_tree.column("status", width=240, anchor=tk.W)
        self.queue_tree.tag_configure("pending", background="white")
        self.queue_tree.tag_configure("processing", background="#eff6ff")
        self.queue_tree.tag_configure("done", background="#ecfdf5")
        self.queue_tree.tag_configure("error", background="#fef2f2")
        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=tree_scroll.set)
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        queue_actions = ttk.Frame(queue_section, style="Card.TFrame")
        queue_actions.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(queue_actions, text="Remover selecionado", style="Danger.TButton", command=self.remove_selected).pack(side=tk.LEFT)
        progress_section = ttk.Frame(card_inner, style="Card.TFrame")
        progress_section.pack(fill=tk.X, pady=(18, 0))
        ttk.Label(progress_section, text="Progresso", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 8))
        self.status_label = ttk.Label(progress_section, text="", style="BigStatus.TLabel")
        self.status_label.pack(anchor=tk.W, pady=(0, 4))
        self.detail_label = ttk.Label(progress_section, text="", style="Status.TLabel")
        self.detail_label.pack(anchor=tk.W, pady=(0, 10))
        progress_row = ttk.Frame(progress_section, style="Card.TFrame")
        progress_row.pack(fill=tk.X)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_row, variable=self.progress_var, maximum=100, style="Modern.Horizontal.TProgressbar")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.percentage_label = ttk.Label(progress_row, text="0%", style="BigStatus.TLabel")
        self.percentage_label.pack(side=tk.LEFT, padx=(12, 0))
        self.file_progress_label = ttk.Label(progress_section, text="", style="Status.TLabel")
        self.file_progress_label.pack(anchor=tk.W, pady=(8, 0))

        log_section = ttk.Frame(card_inner, style="Card.TFrame")
        log_section.pack(fill=tk.BOTH, expand=True, pady=(18, 0))
        ttk.Label(log_section, text="Logs de execução", style="Section.TLabel").pack(anchor=tk.W, pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            log_section,
            height=10,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state=tk.DISABLED)
        self.finish_frame = ttk.Frame(card_inner, style="Card.TFrame")
        self.finish_open_button = ttk.Button(self.finish_frame, text="Abrir ata", style="Accent.TButton", command=self.open_transcription)
        self.finish_restart_button = ttk.Button(self.finish_frame, text="Transcrever outro arquivo", style="Success.TButton", command=self.reset_for_new)
        self.finish_open_button.pack(side=tk.LEFT)
        self.finish_restart_button.pack(side=tk.LEFT, padx=(10, 0))

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

        if self.current_log_file:
            self.current_log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.current_log_file.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def _clear_logs(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
    def _supported_directory(self) -> str:
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            return str(downloads)
        return str(Path.home())
    def _display_name(self, path: str | Path) -> str:
        file_path = Path(path)
        parent = file_path.parent.name
        if parent and parent != file_path.anchor:
            return f"{file_path.name}  •  {parent}"
        return file_path.name
    def _refresh_queue_view(self) -> None:
        for row in self.queue_tree.get_children():
            self.queue_tree.delete(row)
        for index, item in enumerate(self.queue):
            self.queue_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(self._display_name(item["path"]), item["status"]),
                tags=(item.get("tag", "pending"),),
            )
    def _update_queue_row(self, index: int, status: str, tag: str) -> None:
        if 0 <= index < len(self.queue):
            self.queue[index]["status"] = status
            self.queue[index]["tag"] = tag
            row_id = str(index)
            if self.queue_tree.exists(row_id):
                self.queue_tree.item(row_id, values=(self._display_name(self.queue[index]["path"]), status), tags=(tag,))
    def _update_progress(self, percent: int, status: str, detail: str, current_file_progress: str = "") -> None:
        self.progress_var.set(max(0, min(100, percent)))
        self.percentage_label.config(text=f"{max(0, min(100, percent))}%")
        self.status_label.config(text=status)
        self.detail_label.config(text=detail)
        self.file_progress_label.config(text=current_file_progress)
        self.root.update_idletasks()
    def select_files(self) -> None:
        if self.is_processing:
            return
        initialdir = self._supported_directory()
        filetypes = [
            ("Arquivos de áudio/vídeo", "*.mp4 *.mkv *.mov *.avi *.webm *.ogg *.oga *.opus *.m4a *.mp3 *.wav *.aac"),
            ("Arquivos de áudio", "*.ogg *.oga *.opus *.m4a *.mp3 *.wav *.aac"),
            ("Arquivos de vídeo", "*.mp4 *.mkv *.mov *.avi *.webm"),
            ("Todos os arquivos", "*"),
        ]
        files = filedialog.askopenfilenames(
            parent=self.root,
            title="Selecione um ou mais arquivos para transcrição",
            initialdir=initialdir,
            filetypes=filetypes,
        )
        if not files:
            return
        added = 0
        existing = {item["path"] for item in self.queue}
        for file_name in files:
            resolved = str(Path(file_name).expanduser())
            if resolved not in existing:
                self.queue.append({"path": resolved, "status": "Na fila", "tag": "pending", "result": None})
                existing.add(resolved)
                added += 1
        self.last_directory = Path(files[0]).parent
        self._refresh_queue_view()
        if added:
            self._update_progress(
                int(self.progress_var.get()),
                "Arquivos adicionados",
                f"{added} arquivo(s) novo(s) entraram na fila. Total: {len(self.queue)}.",
            )
    def remove_selected(self) -> None:
        if self.is_processing:
            return
        selection = self.queue_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(self.queue):
            self.queue.pop(index)
            self._refresh_queue_view()
            self._update_progress(0 if not self.queue else int(self.progress_var.get()), "Fila atualizada", f"{len(self.queue)} arquivo(s) na fila.")
    def clear_queue(self) -> None:
        if self.is_processing:
            return
        self.queue.clear()
        self.completed_results.clear()
        self.failed_items.clear()
        self._refresh_queue_view()
        self.finish_frame.pack_forget()
        self._update_progress(0, "Fila limpa", "Selecione arquivos para iniciar uma nova transcrição.")
    def start_transcription(self) -> None:
        if self.is_processing:
            return
        if not self.queue:
            messagebox.showwarning("Aviso", "Adicione pelo menos um arquivo na fila.")
            return
        self.is_processing = True
        self.completed_results.clear()
        self.failed_items.clear()
        self.finish_frame.pack_forget()
        self._clear_logs()
        self.current_log_file = self.output_dir / "logs" / f"transcricao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._append_log("Iniciando processamento da fila...")
        self._append_log(f"Log salvo em: {self.current_log_file}")
        self._update_progress(0, "Preparando processamento", "A fila será processada em sequência.")
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
    def _process_queue(self) -> None:
        total = len(self.queue)
        for index, item in enumerate(self.queue):
            file_path = Path(item["path"])
            self.root.after(0, lambda i=index, p=file_path: self._update_queue_row(i, "Preparando...", "processing"))
            self.root.after(0, lambda p=file_path: self._append_log(f"Arquivo {p.name} entrou em processamento"))

            def progress_callback(percent: int, stage: str, message: str, *, _index=index, _path=file_path) -> None:
                overall = int(((_index + (percent / 100.0)) / total) * 100)
                if percent >= 100 and _index == total - 1:
                    overall = 100
                self.root.after(
                    0,
                    lambda o=overall, s=stage, m=message, fp=_path.name, pp=percent: self._update_progress(
                        o,
                        f"Transcrevendo {_path.name}",
                        m,
                        current_file_progress=f"Arquivo atual: {fp} • etapa: {s} • {pp}%",
                    ),
                )

            def log_callback(message: str, *, _path=file_path) -> None:
                self.root.after(0, lambda m=message, p=_path.name: self._append_log(f"{p}: {m}"))

            try:
                result = transcribe_meeting(
                    file_path,
                    output_dir=self.output_dir,
                    model_name="medium",
                    language="pt",
                    chunk_seconds=45,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                )
                self.completed_results.append(result)
                self.root.after(0, lambda i=index: self._update_queue_row(i, "Concluído", "done"))
                self.root.after(0, lambda p=file_path: self._append_log(f"Arquivo {p.name} concluído"))
                self.root.after(
                    0,
                    lambda p=file_path.name: self._update_progress(
                        int(((index + 1) / total) * 100),
                        f"Concluído: {p}",
                        f"Ata gerada em {result.minutes_path.name}",
                        current_file_progress="",
                    ),
                )
            except Exception as exc:
                self.failed_items.append(f"{file_path.name}: {exc}")
                self.root.after(0, lambda e=str(exc), p=file_path: self._append_log(f"ERRO em {p.name}: {e}"))
                self.root.after(0, lambda i=index, err=str(exc): self._update_queue_row(i, f"Erro: {err}", "error"))
        self.root.after(0, self._finish_processing)
    def _finish_processing(self) -> None:
        self.is_processing = False
        if self.completed_results:
            self.finish_frame.pack(anchor=tk.W, pady=(18, 0))
            self._update_progress(
                100,
                "Processamento concluído",
                f"{len(self.completed_results)} arquivo(s) transcrito(s) com sucesso.",
                current_file_progress="",
            )
        else:
            self._update_progress(0, "Nenhuma transcrição concluída", "Verifique os erros na fila e tente novamente.", current_file_progress="")

        self._append_log("Processamento da fila finalizado")
        if self.failed_items:
            messagebox.showwarning(
                "Alguns arquivos falharam",
                "\n".join(self.failed_items[:6]) + ("\n..." if len(self.failed_items) > 6 else ""),
            )
    def open_transcription(self) -> None:
        if not self.completed_results:
            messagebox.showwarning("Aviso", "Nenhuma ata está disponível para abrir.")
            return
        target = self.completed_results[-1].minutes_path
        if not target.exists():
            messagebox.showerror("Erro", "O arquivo da ata não foi encontrado.")
            return
        try:
            if os.name == "posix":
                subprocess.run(["xdg-open", str(target)], check=False)
            elif os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                messagebox.showinfo("Arquivo gerado", str(target))
        except Exception as exc:
            messagebox.showerror("Erro", f"Não foi possível abrir a ata: {exc}")
    def reset_for_new(self) -> None:
        if self.is_processing:
            messagebox.showinfo("Aguarde", "Finalize o processamento atual antes de reiniciar.")
            return
        self.queue.clear()
        self.completed_results.clear()
        self.failed_items.clear()
        self._refresh_queue_view()
        self.finish_frame.pack_forget()
        self._clear_logs()
        self._update_progress(0, "Pronto para nova fila", "Selecione novos arquivos para transcrever.")
def main() -> None:
    root = tk.Tk()
    app = TranscriptionApp(root)
    root.mainloop()
if __name__ == "__main__":
    main()
