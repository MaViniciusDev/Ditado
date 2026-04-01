#!/usr/bin/env python3
"""Núcleo de transcrição e geração de ata para reuniões.

Centraliza:
- validação de arquivos de áudio/vídeo (incluindo OGG/OGA/OPUS)
- normalização com ffmpeg
- transcrição com Whisper em chunks para progresso real
- identificação heurística de falantes
- resumo com tópicos principais para atas
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections import Counter
import contextlib
import io
import math
import re
import subprocess
import tempfile
from typing import Callable, Optional

import whisper


SUPPORTED_EXTENSIONS = {
    ".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv", ".webm",
    ".ogg", ".oga", ".opus", ".m4a", ".mp3", ".wav", ".aac",
}

PROGRESS_CALLBACK = Callable[[int, str, str], None]

PORTUGUESE_STOPWORDS = {
    "a", "aí", "agora", "ainda", "algo", "alguma", "algumas", "alguns", "ampla", "amplas",
    "amplo", "amplos", "ao", "aos", "apenas", "aquela", "aquelas", "aquele", "aqueles",
    "aqui", "aquilo", "as", "até", "até", "às", "cada", "caminho", "com", "como",
    "contra", "contudo", "da", "das", "de", "dela", "delas", "dele", "deles", "depois",
    "do", "dos", "e", "ela", "elas", "ele", "eles", "em", "entre", "essa", "essas",
    "esse", "esses", "esta", "está", "estão", "estas", "este", "estes", "eu", "foi",
    "foram", "há", "isso", "isto", "já", "lá", "lhe", "lhes", "mais", "mas", "me",
    "mesma", "mesmas", "mesmo", "mesmos", "meu", "meus", "minha", "minhas", "muito",
    "muitos", "na", "não", "nas", "nem", "no", "nos", "nós", "nossa", "nossas", "nosso",
    "nossos", "num", "numa", "o", "os", "ou", "para", "pela", "pelas", "pelo", "pelos",
    "por", "porque", "qual", "quando", "que", "quem", "se", "sem", "seu", "seus", "sob",
    "sobre", "sua", "suas", "também", "te", "tem", "tendo", "ter", "teu", "teus", "um",
    "uma", "umas", "uns", "vou", "você", "vocês", "foque", "ficou", "fica", "ficam",
}


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class SpeakerTurn:
    speaker: str
    start: float
    end: float
    text: str


@dataclass(slots=True)
class MeetingTranscriptResult:
    source_path: Path
    transcript_path: Path
    minutes_path: Path
    duration_seconds: float
    transcript_text: str
    minutes_text: str
    segments: list[TranscriptSegment]
    speaker_turns: list[SpeakerTurn]
    summary_bullets: list[str]
    topics: list[str]
    speaker_mode: str


class TranscriptionError(RuntimeError):
    """Erro de domínio para a pipeline de transcrição."""


@lru_cache(maxsize=4)
def load_whisper_model(model_name: str):
    return whisper.load_model(model_name)


def is_supported_media(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def ensure_file(path: str | Path) -> Path:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")
    if not file_path.is_file():
        raise IsADirectoryError(f"Caminho inválido, esperado arquivo: {file_path}")
    if not is_supported_media(file_path):
        raise ValueError(
            f"Formato não suportado: {file_path.suffix}. "
            f"Use áudio/vídeo compatível com Whisper."
        )
    return file_path


def ensure_output_dir(output_dir: str | Path) -> Path:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def command_exists(command: str) -> bool:
    try:
        subprocess.run(
            [command, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=5,
        )
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def run_command(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise TranscriptionError(stderr or f"Falha ao executar: {' '.join(args)}") from exc


def get_media_duration_seconds(path: Path) -> float:
    if not command_exists("ffprobe"):
        raise TranscriptionError("ffprobe não encontrado no sistema")

    result = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])

    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise TranscriptionError(f"Não foi possível obter a duração de {path.name}") from exc


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def build_chunks(normalized_audio: Path, temp_dir: Path, chunk_seconds: int) -> list[Path]:
    if not command_exists("ffmpeg"):
        raise TranscriptionError("ffmpeg não encontrado no sistema")

    chunk_dir = temp_dir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    pattern = chunk_dir / "chunk_%04d.wav"

    run_command([
        "ffmpeg",
        "-y",
        "-i", str(normalized_audio),
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-reset_timestamps", "1",
        "-acodec", "pcm_s16le",
        str(pattern),
    ])

    chunks = sorted(chunk_dir.glob("chunk_*.wav"))
    if not chunks:
        raise TranscriptionError("Não foi possível dividir o áudio em chunks")
    return chunks


def normalize_media_to_wav(source_path: Path, temp_dir: Path) -> Path:
    normalized = temp_dir / f"{source_path.stem}_normalized.wav"
    run_command([
        "ffmpeg",
        "-y",
        "-i", str(source_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(normalized),
    ])
    return normalized


def progress_report(callback: Optional[PROGRESS_CALLBACK], percent: int, stage: str, message: str) -> None:
    if callback is not None:
        callback(max(0, min(100, int(percent))), stage, message)


def transcribe_chunk(model, chunk_path: Path, language: str) -> list[TranscriptSegment]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = model.transcribe(
            str(chunk_path),
            language=language,
            task="transcribe",
            verbose=False,
            fp16=False,
            condition_on_previous_text=False,
            temperature=0,
        )
    segments: list[TranscriptSegment] = []
    for segment in result.get("segments", []):
        text = normalize_text(segment.get("text", ""))
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=float(segment.get("start", 0.0)),
                end=float(segment.get("end", 0.0)),
                text=text,
            )
        )
    return segments


def transcribe_chunks(
    model,
    chunks: list[Path],
    chunk_seconds: int,
    language: str,
    callback: Optional[PROGRESS_CALLBACK],
) -> list[TranscriptSegment]:
    total = len(chunks)
    all_segments: list[TranscriptSegment] = []

    for index, chunk in enumerate(chunks, start=1):
        percent = 10 + int((index - 1) * 75 / max(total, 1))
        progress_report(
            callback,
            percent,
            "transcribing",
            f"Transcrevendo parte {index}/{total}...",
        )
        chunk_segments = transcribe_chunk(model, chunk, language)
        offset = (index - 1) * chunk_seconds
        for segment in chunk_segments:
            all_segments.append(
                TranscriptSegment(
                    start=segment.start + offset,
                    end=segment.end + offset,
                    text=segment.text,
                )
            )

    return all_segments


def infer_speaker_turns(segments: list[TranscriptSegment]) -> list[SpeakerTurn]:
    if not segments:
        return []

    turns: list[SpeakerTurn] = []
    current_speaker = 1
    current_start = segments[0].start
    current_end = segments[0].end
    current_texts = [segments[0].text]

    for segment in segments[1:]:
        gap = segment.start - current_end
        # Gaps maiores sugerem mudança de falante; a alternância é heurística.
        if gap >= 1.2:
            turns.append(
                SpeakerTurn(
                    speaker=f"Falante {current_speaker}",
                    start=current_start,
                    end=current_end,
                    text=normalize_text(" ".join(current_texts)),
                )
            )
            current_speaker = 2 if current_speaker == 1 else 1
            current_start = segment.start
            current_end = segment.end
            current_texts = [segment.text]
            continue

        current_end = max(current_end, segment.end)
        current_texts.append(segment.text)

    turns.append(
        SpeakerTurn(
            speaker=f"Falante {current_speaker}",
            start=current_start,
            end=current_end,
            text=normalize_text(" ".join(current_texts)),
        )
    )
    return turns


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+|\n+", normalize_text(text))
    return [piece.strip() for piece in pieces if len(piece.strip()) > 20]


def tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-zà-ÿ]+", text.lower())


def extract_topics(text: str, limit: int = 8) -> list[str]:
    words = [word for word in tokenize_words(text) if word not in PORTUGUESE_STOPWORDS and len(word) > 2]
    if not words:
        return []

    frequencies = Counter(words)
    bigrams = Counter(
        f"{words[i]} {words[i + 1]}"
        for i in range(len(words) - 1)
        if words[i] != words[i + 1]
    )

    combined = Counter()
    combined.update({word: freq for word, freq in frequencies.items()})
    combined.update({phrase: freq * 2 for phrase, freq in bigrams.items() if freq >= 2})

    ordered = [item for item, _ in combined.most_common(limit * 2)]
    topics: list[str] = []
    for item in ordered:
        if item not in topics:
            topics.append(item)
        if len(topics) >= limit:
            break
    return topics


def summarize_text(text: str, limit: int = 5) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []

    words = [word for word in tokenize_words(text) if word not in PORTUGUESE_STOPWORDS and len(word) > 2]
    frequencies = Counter(words)
    if not frequencies:
        return sentences[:limit]

    scores: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        sentence_words = [word for word in tokenize_words(sentence) if word not in PORTUGUESE_STOPWORDS and len(word) > 2]
        if not sentence_words:
            continue
        score = sum(frequencies[word] for word in sentence_words) / math.log(len(sentence_words) + 1.5)
        scores.append((score, index, sentence))

    if not scores:
        return sentences[:limit]

    scores.sort(key=lambda item: (-item[0], item[1]))
    chosen = sorted(scores[:limit], key=lambda item: item[1])
    return [sentence.strip() for _, _, sentence in chosen]


def build_minutes_text(
    source_path: Path,
    duration_seconds: float,
    transcript_text: str,
    turns: list[SpeakerTurn],
    summary_bullets: list[str],
    topics: list[str],
    speaker_mode: str,
) -> str:
    lines: list[str] = []
    lines.append(f"# Ata automática — {source_path.name}")
    lines.append("")
    lines.append(f"**Arquivo de origem:** `{source_path}`")
    lines.append(f"**Duração estimada:** {format_timestamp(duration_seconds)}")
    lines.append(f"**Diarização:** {speaker_mode}")
    lines.append("")
    lines.append("> Observação: quando não há biblioteca de diarização especializada disponível, os falantes são estimados por heurística de pausas entre trechos.")
    lines.append("")

    lines.append("## Resumo executivo")
    if summary_bullets:
        for bullet in summary_bullets:
            lines.append(f"- {bullet}")
    else:
        lines.append("- Resumo não pôde ser gerado automaticamente.")
    lines.append("")

    lines.append("## Tópicos principais")
    if topics:
        for topic in topics:
            lines.append(f"- {topic}")
    else:
        lines.append("- Sem tópicos principais identificados.")
    lines.append("")

    lines.append("## Participantes estimados")
    speaker_names = sorted({turn.speaker for turn in turns})
    if speaker_names:
        for speaker in speaker_names:
            lines.append(f"- {speaker}")
    else:
        lines.append("- Nenhum falante estimado.")
    lines.append("")

    lines.append("## Transcrição por falante")
    if turns:
        for turn in turns:
            lines.append(
                f"- **{turn.speaker}** [{format_timestamp(turn.start)} - {format_timestamp(turn.end)}]: {turn.text}"
            )
    else:
        lines.append("- Transcrição vazia.")
    lines.append("")

    lines.append("## Transcrição completa")
    lines.append(transcript_text or "")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def transcribe_meeting(
    source_path: str | Path,
    output_dir: str | Path = "./transcricoes",
    *,
    model_name: str = "medium",
    language: str = "pt",
    chunk_seconds: int = 45,
    progress_callback: Optional[PROGRESS_CALLBACK] = None,
) -> MeetingTranscriptResult:
    source = ensure_file(source_path)
    output_path = ensure_output_dir(output_dir)

    if chunk_seconds < 15:
        raise ValueError("chunk_seconds deve ser de pelo menos 15 segundos")

    progress_report(progress_callback, 0, "starting", f"Preparando {source.name}...")

    duration_seconds = get_media_duration_seconds(source)

    with tempfile.TemporaryDirectory(prefix="transcricao_", dir=str(output_path)) as temp_dir_name:
        temp_dir = Path(temp_dir_name)

        progress_report(progress_callback, 5, "normalizing", "Normalizando mídia...")
        normalized_audio = normalize_media_to_wav(source, temp_dir)

        progress_report(progress_callback, 10, "chunking", "Dividindo em partes para acompanhar o progresso...")
        chunks = build_chunks(normalized_audio, temp_dir, chunk_seconds)

        model = load_whisper_model(model_name)
        segments = transcribe_chunks(model, chunks, chunk_seconds, language, progress_callback)

        transcript_lines = [
            f"[{format_timestamp(segment.start)} - {format_timestamp(segment.end)}] {segment.text}"
            for segment in segments
        ]
        transcript_text = "\n".join(transcript_lines).strip() + ("\n" if transcript_lines else "")

        progress_report(progress_callback, 88, "analysis", "Organizando falantes e preparando a ata...")
        speaker_turns = infer_speaker_turns(segments)
        summary_bullets = summarize_text(transcript_text, limit=5)
        topics = extract_topics(transcript_text, limit=8)

        speaker_mode = "Falantes estimados localmente por heurística de pausas"
        minutes_text = build_minutes_text(
            source_path=source,
            duration_seconds=duration_seconds,
            transcript_text=transcript_text,
            turns=speaker_turns,
            summary_bullets=summary_bullets,
            topics=topics,
            speaker_mode=speaker_mode,
        )

        transcript_path = output_path / f"{source.stem}_transcricao.txt"
        minutes_path = output_path / f"{source.stem}_ata.md"

        progress_report(progress_callback, 94, "writing", "Salvando arquivos de saída...")
        transcript_path.write_text(transcript_text, encoding="utf-8")
        minutes_path.write_text(minutes_text, encoding="utf-8")
        progress_report(progress_callback, 100, "done", "Concluído")

    return MeetingTranscriptResult(
        source_path=source,
        transcript_path=transcript_path,
        minutes_path=minutes_path,
        duration_seconds=duration_seconds,
        transcript_text=transcript_text,
        minutes_text=minutes_text,
        segments=segments,
        speaker_turns=speaker_turns,
        summary_bullets=summary_bullets,
        topics=topics,
        speaker_mode=speaker_mode,
    )


def extract_and_transcribe(video_path: str, output_dir: str = "./transcricoes") -> str:
    """Compatibilidade com a interface/CLI antiga.

    Agora gera ata em Markdown além da transcrição completa.
    Retorna o caminho da ata.
    """

    result = transcribe_meeting(video_path, output_dir=output_dir)
    return str(result.minutes_path)


def main() -> None:
    import sys

    if len(sys.argv) > 1:
        source = sys.argv[1]
    else:
        source = input("Digite o caminho do arquivo de áudio/vídeo: ").strip()

    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./transcricoes"

    def cli_progress(percent: int, stage: str, message: str) -> None:
        print(f"[{percent:3d}%] {stage}: {message}")

    try:
        result = transcribe_meeting(source, output_dir=output_dir, progress_callback=cli_progress)
        print("\nAta gerada com sucesso:")
        print(result.minutes_path)
        print("Transcrição completa:")
        print(result.transcript_path)
    except Exception as exc:
        print(f"Erro: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

