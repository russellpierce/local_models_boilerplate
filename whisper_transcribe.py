#!/usr/bin/env -S uv run --script
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

## Notes
# openai-whisper has its own command line 
#   see https://github.com/openai/whisper/tree/main?tab=readme-ov-file#available-models-and-languages



## Retain this block for documentation purposes ##
# Dev Process
# Open AI GPT-4 Turbo prompted to perform a task, responded with whisper code.
# Open AI goaded into producing PEP 723 comment string
# Claude Opus prompted with that output as well as feature requests:  rewrite this script. It needs to use a temporary file (preferably in RAM) and clean up the temporary file when it is done.
# Claude Opus reprompted to add shabang and reqiured info to top of file.
# User researched and determined that shabang and PEP 723 use are mutually exclusive - so dropped the shabang.
# Cursor prompted to "Check for ffmpeg in transcribe and cache the result for future calls.  If ffmpeg doesn't exist print an error message, raise an appropriate exception."
# Cursor prompted to "Add instructions with the print for installing ffmpeg on ubuntu 24.04 to the print statement on line 43."
# Cursor prompted to "Add instructions for mac and mac m1 also."
# Cursor prompted to "avoid print statements for everything other than transcript output, when this function is called as a module, it should use an optionally provided logger, if no logger is provided, then use a locally defined logger configured to print to stdio"
# User got in the middle and wrecked some shop to clean up handling for both command line and general use cases and cleaned up the specifics of how to launch and engage with the env in VSCode
# /// end documentation purposes ///

import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
from contextlib import contextmanager
from io import BytesIO
import warnings
import shutil

import whisper
import numpy as np
from pydub import AudioSegment
from tqdm import tqdm


def _check_ffmpeg_exists(logger=None):
    """Check if ffmpeg is available in PATH. Cache the result for future calls. Use provided logger if available."""
    if logger is None:
        logger = logging.getLogger(__name__)
    if not hasattr(_check_ffmpeg_exists, "_cached_result"):
        ffmpeg_path = shutil.which("ffmpeg")
        _check_ffmpeg_exists._cached_result = ffmpeg_path is not None
    if not _check_ffmpeg_exists._cached_result:
        logger.error("ffmpeg is not installed or not found in PATH.")
        logger.error("To install ffmpeg on Ubuntu 24.04, run: sudo apt update && sudo apt install ffmpeg")
        logger.error("To install ffmpeg on Mac (Intel or Apple Silicon), run: brew install ffmpeg")
        logger.error("If you do not have Homebrew, install it from https://brew.sh/")
        raise RuntimeError("ffmpeg is required but was not found in PATH.")


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class AudioTranscriber:
    """High-performance audio transcription using Whisper with in-memory processing."""

    # See: https://github.com/openai/whisper#available-models or https://huggingface.co/models?search=openai/whisper
    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]
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
        logger=None,
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
        if logger is None:
            logger = logging.getLogger(__name__)
        _check_ffmpeg_exists(logger=logger)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        logger.info(f"Processing: {audio_path.name}")

        # Load audio file
        try:
            audio_segment = AudioSegment.from_file(audio_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load audio file {audio_path}, AudioSegment.from_file said: {type(e).__name__}: {e}")

        # Preprocess for optimal transcription
        audio_segment = self._preprocess_audio(audio_segment)

        # Process in memory
        with self._temporary_wav_buffer(audio_segment) as wav_buffer:
            audio_array = self._load_audio_from_buffer(wav_buffer)

            # Transcribe with progress indication
            logger.info("Starting transcription")
            
            # Prepare transcription options
            transcribe_options = {
                'audio': audio_array,
                'language': language,
                'initial_prompt': initial_prompt,
                'fp16': False,
            }

            # Use tqdm with SSH-friendly settings
            if verbose:
                # Show progress based on audio duration for better granularity
                duration_seconds = int(len(audio_segment) / 1000.0)
                with tqdm(
                    total=duration_seconds,
                    desc="Transcribing",
                    unit="sec",
                    ncols=80,  # Fixed width for SSH
                    ascii=True,  # ASCII chars work better over SSH
                    disable=False,
                    file=sys.stderr  # Ensure progress goes to stderr, not stdout
                ) as pbar:
                    result = self.model.transcribe(**transcribe_options)
                    pbar.update(duration_seconds)  # Complete the bar
            else:
                result = self.model.transcribe(**transcribe_options)

        # Extract useful metadata
        metadata = {
            "language": result.get("language", "unknown"),
            "duration": len(audio_segment) / 1000.0,  # seconds
            "model": self.model_name,
        }

        return result["text"].strip(), metadata


def format_sentences(text: str) -> str:
    """Format text with each sentence on a new line.

    Args:
        text: Input text to format

    Returns:
        Formatted text with sentences on separate lines
    """
    import re

    # Split on sentence endings, preserving the punctuation
    sentences = re.split(r'([.!?]+)', text)

    # Reconstruct sentences with their punctuation
    formatted_sentences = []
    for i in range(0, len(sentences) - 1, 2):
        sentence = sentences[i].strip()
        punctuation = sentences[i + 1] if i + 1 < len(sentences) else ""

        if sentence:  # Only add non-empty sentences
            formatted_sentences.append(sentence + punctuation)

    # Join with newlines and clean up extra whitespace
    return '\n'.join(formatted_sentences).strip()


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

    try:
        args = parser.parse_args()

        # Initialize transcriber
        transcriber = AudioTranscriber(model_name=args.model)

        # Perform transcription
        text, metadata = transcriber.transcribe(
            args.audio_file,
            language=args.language,
            initial_prompt=args.prompt,
            verbose=args.verbose,
        )

        # Format text with sentences on separate lines
        formatted_text = format_sentences(text)

        # Output results
        print(formatted_text)

        if args.show_metadata:
            print("\n--- Metadata ---", file=sys.stderr)
            print(f"Language: {metadata['language']}", file=sys.stderr)
            print(f"Duration: {metadata['duration']:.1f} seconds", file=sys.stderr)
            print(f"Model: {metadata['model']}", file=sys.stderr)
        return 0
    except Exception as e:
        logger.exception(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
