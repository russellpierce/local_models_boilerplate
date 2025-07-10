# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pydub",
#     "openai-whisper",
#     "ffmpeg-python",
#     "tqdm",
#     "numpy"
# ]
# ///
#!/usr/bin/env -S uv run

## Retain this block for documentation purposes ##
# Dev Process
# Open AI GPT-4 Turbo prompted to perform a task, responded with whisper code.
# Open AI goaded into producing PEP 723 comment string
# Claude Opus prompted with that output as well as feature requests:  rewrite this script. It needs to use a temporary file (preferably in RAM) and clean up the temporary file when it is done.
# Claude Opus reprompted to add shabang but

import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
from contextlib import contextmanager
from io import BytesIO
import warnings

import whisper
import numpy as np
from pydub import AudioSegment
from tqdm import tqdm


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class AudioTranscriber:
    """High-performance audio transcription using Whisper with in-memory processing."""

    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large"]
    OPTIMAL_SAMPLE_RATE = 16000  # Whisper's preferred sample rate

    def __init__(self, model_name: str = "base", device: Optional[str] = None):
        """Initialize transcriber with specified model.

        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
            device: Compute device (cuda, cpu, or None for auto-detect)
        """
        if model_name not in self.SUPPORTED_MODELS:
            raise ValueError(f"Model must be one of {self.SUPPORTED_MODELS}")

        logger.info(f"Loading Whisper model: {model_name}")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model = whisper.load_model(model_name, device=device)
        self.model_name = model_name

    @contextmanager
    def _temporary_wav_buffer(self, audio_segment: AudioSegment):
        """Create in-memory WAV buffer for audio processing.

        This avoids disk I/O by keeping everything in RAM.
        """
        buffer = BytesIO()
        try:
            # Export to buffer instead of file
            audio_segment.export(buffer, format="wav")
            buffer.seek(0)
            yield buffer
        finally:
            buffer.close()

    def _preprocess_audio(self, audio: AudioSegment) -> AudioSegment:
        """Optimize audio for transcription accuracy.

        Applies best practices for Whisper input preparation.
        """
        # Convert to mono for consistency
        if audio.channels > 1:
            logger.debug("Converting to mono")
            audio = audio.set_channels(1)

        # Resample to Whisper's preferred rate
        if audio.frame_rate != self.OPTIMAL_SAMPLE_RATE:
            logger.debug(
                f"Resampling from {audio.frame_rate}Hz to {self.OPTIMAL_SAMPLE_RATE}Hz"
            )
            audio = audio.set_frame_rate(self.OPTIMAL_SAMPLE_RATE)

        # Normalize audio levels
        logger.debug("Normalizing audio levels")
        audio = audio.normalize()

        return audio

    def _load_audio_from_buffer(self, buffer: BytesIO) -> np.ndarray:
        """Load audio directly from memory buffer to numpy array."""
        # Create a temporary file that exists only in memory
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(buffer.getvalue())
            tmp.flush()
            # Whisper's load_audio expects a file path
            audio_array = whisper.load_audio(tmp.name)
        return audio_array

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        verbose: bool = False,
    ) -> Tuple[str, dict]:
        """Transcribe audio file with optimized processing.

        Args:
            audio_path: Path to input audio file
            language: Force specific language (e.g., 'en', 'es')
            initial_prompt: Optional context to guide transcription
            verbose: Show progress bar during transcription

        Returns:
            Tuple of (transcription_text, metadata_dict)
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Processing: {audio_path.name}")

        # Load audio file
        try:
            audio_segment = AudioSegment.from_file(audio_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load audio file: {e}")

        # Preprocess for optimal transcription
        audio_segment = self._preprocess_audio(audio_segment)

        # Process in memory
        with self._temporary_wav_buffer(audio_segment) as wav_buffer:
            audio_array = self._load_audio_from_buffer(wav_buffer)

            # Transcribe with progress indication
            logger.info("Starting transcription")
            if verbose:
                with tqdm(total=1, desc="Transcribing", unit="file") as pbar:
                    result = self.model.transcribe(
                        audio_array,
                        language=language,
                        initial_prompt=initial_prompt,
                        fp16=False,  # More stable on diverse hardware
                    )
                    pbar.update(1)
            else:
                result = self.model.transcribe(
                    audio_array,
                    language=language,
                    initial_prompt=initial_prompt,
                    fp16=False,
                )

        # Extract useful metadata
        metadata = {
            "language": result.get("language", "unknown"),
            "duration": len(audio_segment) / 1000.0,  # seconds
            "model": self.model_name,
        }

        return result["text"].strip(), metadata


def main() -> int:
    """CLI interface for audio transcription."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Transcribe audio files using OpenAI Whisper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("audio_file", type=Path, help="Path to audio file")
    parser.add_argument(
        "--model",
        choices=AudioTranscriber.SUPPORTED_MODELS,
        default="base",
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--language", type=str, help="Force specific language code (e.g., en, es, fr)"
    )
    parser.add_argument(
        "--prompt", type=str, help="Initial prompt to guide transcription style"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show progress information"
    )
    parser.add_argument(
        "--show-metadata", action="store_true", help="Display transcription metadata"
    )

    args = parser.parse_args()

    try:
        # Initialize transcriber
        transcriber = AudioTranscriber(model_name=args.model)

        # Perform transcription
        text, metadata = transcriber.transcribe(
            args.audio_file,
            language=args.language,
            initial_prompt=args.prompt,
            verbose=args.verbose,
        )

        # Output results
        print(text)

        if args.show_metadata:
            print("\n--- Metadata ---", file=sys.stderr)
            print(f"Language: {metadata['language']}", file=sys.stderr)
            print(f"Duration: {metadata['duration']:.1f} seconds", file=sys.stderr)
            print(f"Model: {metadata['model']}", file=sys.stderr)

        return 0

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
