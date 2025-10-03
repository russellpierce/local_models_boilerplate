#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "click>=8.0.0",
#     "inquirer>=3.0.0",
#     "anthropic>=0.40.0",
# ]
# ///

import os
import subprocess
import sys
from pathlib import Path
import shlex
import time
import click
import inquirer
import anthropic

# Configuration
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"


# ============================================================================
# File Selection and UI Helpers
# ============================================================================

def fetch_audio_files():
    """Fetch list of recent audio files from common locations"""
    # Common audio file locations in WSL2
    search_paths = [
        Path("/mnt/c/Users").glob("*/Downloads"),
        Path("/mnt/c/Users").glob("*/Documents"),
        Path("/mnt/c/Users").glob("*/Music"),
        Path("/mnt/c/Users").glob("*/Desktop"),
        Path("/mnt/c/Users").glob("*/Documents/Sound Recordings"),
        [Path.home() / "Downloads"],
        [Path.home() / "Documents"],
        [Path.home()],
        [Path.cwd()],
    ]

    audio_extensions = {'.m4a', '.mp3', '.wav', '.mp4', '.avi', '.mov', '.flac', '.ogg'}
    audio_files = []

    # Flatten and search all paths
    all_paths = []
    for path_group in search_paths:
        if isinstance(path_group, list):
            all_paths.extend(path_group)
        else:
            all_paths.extend(path_group)

    for search_path in all_paths:
        if search_path.exists() and search_path.is_dir():
            try:
                for file in search_path.iterdir():
                    if file.is_file() and file.suffix.lower() in audio_extensions:
                        audio_files.append(file)
            except PermissionError:
                # Retry once after 1 second
                time.sleep(1)
                try:
                    for file in search_path.iterdir():
                        if file.is_file() and file.suffix.lower() in audio_extensions:
                            audio_files.append(file)
                except PermissionError:
                    continue

    if audio_files:
        # Sort by modification time (newest first), limit to 15 most recent
        audio_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        audio_files = audio_files[:15]

    return audio_files


def select_audio_file(audio_files=None):
    """Smart file selection with recent files and manual entry"""
    if audio_files is None:
        print("\nLooking for recent audio files...")
        audio_files = fetch_audio_files()

    if audio_files:
        choices = [str(f) for f in audio_files]
        choices.append("📁 Browse for file manually...")

        questions = [
            inquirer.List('audio_file',
                         message="Select an audio file",
                         choices=choices,
                         ),
        ]

        answers = inquirer.prompt(questions)
        if answers and answers['audio_file'] != "📁 Browse for file manually...":
            return answers['audio_file']

    # Manual entry fallback
    while True:
        file_path = click.prompt("Enter audio file path", type=str).strip().strip('"\'')

        # Handle Windows paths from clipboard
        if file_path.startswith('C:') or file_path.startswith('c:'):
            file_path = file_path.replace('\\', '/')
            file_path = '/mnt/c' + file_path[2:]

        path = Path(file_path)
        if path.exists() and path.is_file():
            return str(path.absolute())
        else:
            click.echo(f"File not found: {file_path}", err=True)


def select_model():
    """Prompt user to select transcription model"""
    models = ["large", "medium.en", "turbo"]
    questions = [
        inquirer.List('model',
                     message="Select transcription model",
                     choices=models,
                     ),
    ]
    answers = inquirer.prompt(questions)
    if answers:
        return answers['model']
    else:
        click.echo("No model selected. Exiting.", err=True)
        sys.exit(1)


def collect_prompt_interactively():
    """Collect prompt interactively from user"""
    print("\nWould you like to provide an initial prompt to guide the transcription?")
    questions = [
        inquirer.List('provide_prompt',
                     message="Initial prompt",
                     choices=[
                         "📝 Enter a custom prompt",
                         "⏭️ Skip (no prompt)",
                     ],
                     ),
    ]

    answers = inquirer.prompt(questions)
    if answers and answers['provide_prompt'].startswith("📝"):
        prompt = click.prompt("Enter your initial prompt for transcription", type=str)
        return prompt.strip()
    else:
        return None


def collect_summary_prompt_interactively():
    """Collect summary system prompt interactively from user"""
    default_prompt = "Process the following transcript and attempt to provide the full content, but in format that logically flows and has structure and headings."

    print(f"\nDefault summary prompt: \"{default_prompt}\"")
    print("\nWould you like to customize the summary prompt?")

    questions = [
        inquirer.List('customize_prompt',
                     message="Summary prompt",
                     choices=[
                         "✓ Use default prompt",
                         "✏️ Customize the summary prompt",
                     ],
                     ),
    ]

    answers = inquirer.prompt(questions)
    if answers and answers['customize_prompt'].startswith("✏️"):
        custom_prompt = click.prompt("Enter your custom summary prompt", type=str)
        return custom_prompt.strip()
    else:
        return None


def select_optional_parameters(clean, summary, slack):
    """Allow user to select optional parameters if not provided via CLI"""
    print("\nSelect transcript processing level:")

    # Determine default processing level based on current flags
    if summary:
        default_level = 'summary'
    elif clean:
        default_level = 'clean'
    else:
        default_level = 'raw'

    # Question 1: Select processing level (sequential pipeline)
    processing_choices = [
        'Raw transcript only (no AI processing)',
        'Clean transcript (fix transcription errors)',
        'Summarize transcript (clean + add structure/headings)',
    ]

    questions = [
        inquirer.List('processing_level',
                     message="Select transcript processing level",
                     choices=processing_choices,
                     default=processing_choices[['raw', 'clean', 'summary'].index(default_level)],
                     ),
        inquirer.Confirm('slack_format',
                        message="Apply Slack formatting to final output?",
                        default=slack,
                        ),
    ]

    answers = inquirer.prompt(questions)
    if answers:
        # Map user selection to flags
        selected_level = answers['processing_level']
        if 'Raw' in selected_level:
            return {'clean': False, 'summary': False, 'slack': answers['slack_format']}
        elif 'Clean' in selected_level:
            return {'clean': True, 'summary': False, 'slack': answers['slack_format']}
        else:  # Summarize
            return {'clean': True, 'summary': True, 'slack': answers['slack_format']}
    else:
        return {'clean': clean, 'summary': summary, 'slack': slack}


# ============================================================================
# Anthropic API Functions
# ============================================================================

def clean_transcript(transcript_text, api_key, mode="clean", format_slack=False, system_prompt=None):
    """Clean or summarize transcript using Anthropic API"""
    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build prompt based on mode
        if mode == "summary":
            default_summary_prompt = """Process the following transcript and attempt to provide the full content, but in format that logically flows and has structure and headings."""
            prompt = system_prompt if system_prompt else default_summary_prompt
        else:  # mode == "clean"
            prompt = """The following is an audio recording transcript. Process it to remove any clear transcription errors."""

        if format_slack:
            prompt += " Format as a Slack message."

        prompt += f"""

        Transcript:
        {transcript_text}"""

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=8192,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response.content[0].text

    except Exception as e:
        print(f"Warning: Failed to clean transcript with Anthropic API: {e}")
        return None


# ============================================================================
# SSH Command Execution
# ============================================================================

def run_command(command, description):
    """Execute shell command with error handling"""
    print(f"Running: {description}")
    print(f"Command: {command}")

    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error: {description} failed")
        print(f"stderr: {result.stderr}")
        return False

    if result.stdout:
        print(f"stdout: {result.stdout}")

    return True


def test_ssh_connection(host):
    """Test SSH connection to remote host"""
    print(f"\nTesting SSH connection to {host}...")

    # Use BatchMode to prevent interactive prompts, ConnectTimeout for quick failure
    test_cmd = f'ssh -o ConnectTimeout=5 -o BatchMode=yes {host} echo "connection successful"'

    result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"✗ SSH connection failed to {host}")
        if result.stderr:
            print(f"Error: {result.stderr.strip()}")
        return False

    print(f"✓ SSH connection successful to {host}")
    return True


# ============================================================================
# Main Transcription Orchestration
# ============================================================================

def transcribe_audio(transcript_host, audio_file_path, model, clean_transcript_flag=False, summary_mode=False, format_slack=False, output_dir=None, initial_prompt=None, summary_system_prompt=None):
    """Main transcription workflow - orchestrates remote Whisper processing with optional AI enhancement"""

    if not audio_file_path:
        print("No audio file selected. Exiting.")
        return False

    audio_file = Path(audio_file_path)
    if not audio_file.exists():
        print(f"Audio file not found: {audio_file_path}")
        return False

    audio_filename = audio_file.name
    text_filename = audio_file.stem + ".txt"

    if output_dir is None:
        output_dir = audio_file.parent

    output_path = Path(output_dir) / text_filename

    print(f"\n{'='*70}")
    print(f"Starting transcription with the following configuration:")
    print(f"{'='*70}")
    print(f"  Audio file:     {audio_file_path}")
    print(f"  Remote host:    {transcript_host}")
    print(f"  Model:          {model}")
    print(f"  Output dir:     {output_dir}")
    print(f"  Clean:          {clean_transcript_flag}")
    print(f"  Summary:        {summary_mode}")
    print(f"  Slack format:   {format_slack}")
    print(f"  Initial prompt: {initial_prompt if initial_prompt else 'None'}")
    print(f"{'='*70}\n")

    try:
        # Step 1: Copy transcription script to remote host
        print("\n=== Step 1: Copying transcription script to remote host ===")
        script_copy_cmd = f"scp whisper_transcribe.py {transcript_host}:~/whisper_transcribe.py"
        if not run_command(script_copy_cmd, "Copy transcription script to remote host"):
            return False

        # Step 2: Copy audio file to remote host
        print("\n=== Step 2: Copying audio file to remote host ===")
        audio_copy_cmd = f'scp "{audio_file_path}" {transcript_host}:/tmp/"{audio_filename}"'
        if not run_command(audio_copy_cmd, "Copy audio file to remote host"):
            return False

        # Step 3: Execute transcription on remote host
        print("\n=== Step 3: Running transcription on remote host ===")

        # Build remote command - will be passed through SSH to remote shell
        remote_cmd = '.local/bin/uv run whisper_transcribe.py'
        remote_cmd += f' --model {model}'
        remote_cmd += ' --language en'
        remote_cmd += ' --verbose'

        if initial_prompt:
            remote_cmd += f' --prompt {shlex.quote(initial_prompt)}'

        remote_cmd += f' {shlex.quote(f"/tmp/{audio_filename}")}'
        remote_cmd += f' > {shlex.quote(f"/tmp/{text_filename}")}'

        # Execute via SSH (quote the entire remote command once)
        transcribe_cmd = f'ssh {transcript_host} {shlex.quote(remote_cmd)}'

        if not run_command(transcribe_cmd, "Execute transcription on remote host"):
            return False

        # Step 4: Copy transcript back to local host
        print("\n=== Step 4: Copying transcript back to local host ===")
        transcript_copy_cmd = f'scp {transcript_host}:"/tmp/{text_filename}" "{output_path}"'
        if not run_command(transcript_copy_cmd, "Copy transcript back to local host"):
            return False

        # Step 5: Process transcript with Anthropic API (if requested)
        if clean_transcript_flag or summary_mode:
            print("\n=== Step 5: Processing transcript with Anthropic API ===")

            api_key = os.getenv('ANTHROPIC_KEY')
            if not api_key:
                print("Warning: ANTHROPIC_KEY environment variable not set. Skipping transcript processing.")
            else:
                try:
                    # Read the original transcript
                    with open(output_path, 'r', encoding='utf-8') as f:
                        current_transcript = f.read()

                    # Step 5a: Clean transcript (if cleaning or summarizing)
                    if clean_transcript_flag or summary_mode:
                        print("Cleaning transcript...")
                        cleaned_text = clean_transcript(current_transcript, api_key, mode="clean", format_slack=False)

                        if cleaned_text:
                            cleaned_path = output_path.parent / f"{output_path.stem}_cleaned{output_path.suffix}"
                            with open(cleaned_path, 'w', encoding='utf-8') as f:
                                f.write(cleaned_text)
                            print(f"✓ Cleaned transcript saved to: {cleaned_path}")
                            current_transcript = cleaned_text
                        else:
                            print("✗ Failed to clean transcript, using original for summarization")

                    # Step 5b: Summarize transcript (if summarizing)
                    if summary_mode:
                        print("Summarizing transcript...")
                        summary_text = clean_transcript(current_transcript, api_key, mode="summary", format_slack=False, system_prompt=summary_system_prompt)

                        if summary_text:
                            summary_path = output_path.parent / f"{output_path.stem}_summary{output_path.suffix}"
                            with open(summary_path, 'w', encoding='utf-8') as f:
                                f.write(summary_text)
                            print(f"✓ Summarized transcript saved to: {summary_path}")
                            current_transcript = summary_text
                        else:
                            print("✗ Failed to summarize transcript")

                    # Step 5c: Apply Slack formatting to final processed version (if requested)
                    if format_slack:
                        print("Formatting transcript for Slack...")
                        slack_text = clean_transcript(current_transcript, api_key, mode="clean", format_slack=True)

                        if slack_text:
                            if summary_mode:
                                slack_path = output_path.parent / f"{output_path.stem}_summary_slack{output_path.suffix}"
                            else:
                                slack_path = output_path.parent / f"{output_path.stem}_cleaned_slack{output_path.suffix}"

                            with open(slack_path, 'w', encoding='utf-8') as f:
                                f.write(slack_text)
                            print(f"✓ Slack-formatted transcript saved to: {slack_path}")
                        else:
                            print("✗ Failed to format transcript for Slack")

                except Exception as e:
                    print(f"Error processing transcript: {e}")

        # Step 6: Clean up remote files
        print(f"\n=== Step {'6' if (clean_transcript_flag or summary_mode) else '5'}: Cleaning up remote files ===")
        cleanup_cmd = f'''ssh {transcript_host} "rm -f '/tmp/{audio_filename}' '/tmp/{text_filename}'"'''
        if not run_command(cleanup_cmd, "Clean up remote files"):
            print("Warning: Failed to clean up remote files")

        print(f"\n✅ Transcription completed successfully!")
        print(f"\nOutput files created:")
        print(f"  • Raw transcript: {output_path}")

        if clean_transcript_flag and not summary_mode:
            print(f"  • Cleaned transcript: {output_path.parent / f'{output_path.stem}_cleaned{output_path.suffix}'}")

        if summary_mode:
            print(f"  • Cleaned transcript: {output_path.parent / f'{output_path.stem}_cleaned{output_path.suffix}'}")
            print(f"  • Summary: {output_path.parent / f'{output_path.stem}_summary{output_path.suffix}'}")

        if format_slack:
            if summary_mode:
                print(f"  • Slack formatted: {output_path.parent / f'{output_path.stem}_summary_slack{output_path.suffix}'}")
            else:
                print(f"  • Slack formatted: {output_path.parent / f'{output_path.stem}_cleaned_slack{output_path.suffix}'}")

        return True

    except Exception as e:
        print(f"Error during transcription: {e}")
        return False


# ============================================================================
# CLI Entry Point
# ============================================================================

@click.command()
@click.argument('transcript_host', required=False)
@click.argument('audio_file_path', required=False)
@click.argument('output_dir', required=False)
@click.option('--clean', is_flag=True, help='Clean transcript using Anthropic API')
@click.option('--summary', is_flag=True, help='Generate a structured summary (implies --clean)')
@click.option('--slack', is_flag=True, help='Format output as a Slack message')
@click.option('--prompt', type=str, help='Initial prompt to guide transcription')
@click.option('--summary-prompt', type=str, help='Custom system prompt for summary generation')
def main(transcript_host, audio_file_path, output_dir, clean, summary, slack, prompt, summary_prompt):
    """Transcribe audio files using remote Whisper processing with optional AI enhancement.

    Args:
        transcript_host: Remote host for transcription (optional, prompts if not provided)
        audio_file_path: Path to audio file (optional, prompts if not provided)
        output_dir: Output directory (optional, defaults to audio file directory)
        clean: Clean transcript using Anthropic API
        summary: Generate a structured summary (implies --clean)
        slack: Format output as a Slack message
        prompt: Initial prompt to guide transcription
        summary_prompt: Custom system prompt for summary generation
    """

    # --summary implies --clean
    if summary:
        clean = True

    # Fetch audio file list first (if not provided via CLI)
    audio_files = None
    if not audio_file_path:
        print("\nLooking for recent audio files...")
        audio_files = fetch_audio_files()

    # Get transcript host if not provided, and test SSH connection
    if not transcript_host:
        while True:
            transcript_host = click.prompt("Enter transcript host IP or hostname", type=str).strip()
            if test_ssh_connection(transcript_host):
                break
            print("\nPlease enter a valid transcript host.\n")
    else:
        # Test provided host
        if not test_ssh_connection(transcript_host):
            print(f"\nSSH connection failed to provided host: {transcript_host}")
            while True:
                transcript_host = click.prompt("Enter transcript host IP or hostname", type=str).strip()
                if test_ssh_connection(transcript_host):
                    break
                print("\nPlease enter a valid transcript host.\n")

    # Get audio file if not provided
    if not audio_file_path:
        print("\nPlease select an audio file...")
        audio_file_path = select_audio_file(audio_files)

    if not audio_file_path:
        print("No audio file selected. Exiting.")
        sys.exit(1)

    # Collect prompt interactively if not provided via CLI
    if prompt is None:
        prompt = collect_prompt_interactively()

    # Select optional parameters interactively if not provided via CLI
    ctx = click.get_current_context()
    clean_explicit = ctx.get_parameter_source('clean') == click.core.ParameterSource.COMMANDLINE
    summary_explicit = ctx.get_parameter_source('summary') == click.core.ParameterSource.COMMANDLINE
    slack_explicit = ctx.get_parameter_source('slack') == click.core.ParameterSource.COMMANDLINE

    # Only ask for interactive selection if no flags were explicitly set
    if not (clean_explicit or summary_explicit or slack_explicit):
        options = select_optional_parameters(clean, summary, slack)
        clean = options['clean']
        summary = options['summary']
        slack = options['slack']
    elif summary:  # summary implies clean
        clean = True

    # Collect summary prompt interactively if summary mode is selected and no CLI prompt provided
    if summary and summary_prompt is None:
        summary_prompt = collect_summary_prompt_interactively()

    # Select transcription model
    model = select_model()

    success = transcribe_audio(transcript_host, audio_file_path, model, clean, summary, slack, output_dir, prompt, summary_prompt)

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
