import os
import uuid
import io
import time
import requests # <-- Ensure imported
from flask import Flask, request, jsonify, render_template, send_from_directory
from openai import OpenAI
from pydub import AudioSegment
from math import ceil
import mimetypes # <-- Import for determining file type

# --- Configuration ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm'}
MAX_FILE_SIZE_MB = 24
CHUNK_SIZE_MB = 20

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- API Client Setup ---
# OpenAI
openai_client = OpenAI() # Renamed for clarity
if not openai_client.api_key:
    print("Warning: OPENAI_API_KEY environment variable not set.")

# Pyannote.ai
PYANNOTE_API_KEY = os.getenv("PYANNOTE_API_KEY")
if not PYANNOTE_API_KEY:
    print("Warning: PYANNOTE_API_KEY environment variable not set. Diarization will be unavailable.")

PYANNOTE_HEADERS = {
    "Authorization": f"Bearer {PYANNOTE_API_KEY}"
}
PYANNOTE_MEDIA_URL = "https://api.pyannote.ai/v1/media/input"
PYANNOTE_DIARIZE_URL = "https://api.pyannote.ai/v1/diarize"


# --- Helper Functions ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_extension(filename):
     return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

def transcribe_chunk(file_path, prompt_text, model="gpt-4o-transcribe"):
    """Transcribes a single audio file chunk using OpenAI."""
    print(f"--> Transcribing chunk file: {file_path}")
    try:
        with open(file_path, "rb") as audio_file:
            # Make the API call
            transcription_response = openai_client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="text", # Directly requesting text output
                prompt=prompt_text if prompt_text else None
            )
            # When response_format="text", the response *is* the string
            # No need to access .text or similar attributes.
            # Ensure it's treated as a string.
            transcript_text = str(transcription_response)
            print(f"--> Received transcript part (first 100 chars): '{transcript_text[:100]}...'")
            return transcript_text
    except Exception as e:
        print(f"!!! Error during OpenAI transcription chunk {file_path}: {e}")
        # Optionally log the full exception traceback here if needed
        # import traceback
        # print(traceback.format_exc())
        raise # Re-raise the exception to be caught by the main handler

# Modified post_process_text to accept specific system prompt
def post_process_text(text_to_process, dictionary_prompt, gpt4_system_prompt):
    """Uses GPT-4 Turbo for post-processing with a specific system prompt."""
    try:
        # Use the user-provided system prompt if available, otherwise use a default.
        # Also, incorporate the dictionary terms.
        final_system_prompt = gpt4_system_prompt if gpt4_system_prompt else \
            "You are a helpful assistant tasked with refining an audio transcription."

        if dictionary_prompt:
             final_system_prompt += f"\n\nEnsure the following terms are spelled correctly if they appear: {dictionary_prompt}"

        final_system_prompt += "\n\nCorrect any spelling discrepancies, add necessary punctuation (periods, commas, capitalization), and ensure proper formatting. Only use the context provided in the transcript itself. Output only the corrected text."

        print(f"Using GPT-4.1 system prompt for post-processing: {final_system_prompt[:200]}...") # Log beginning

        # NOTE: Using "gpt-4-turbo" as a modern equivalent for "gpt-4.1" capabilities.
        # Adjust if you have access to a specific "gpt-4.1" model identifier.
        response = openai_client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": text_to_process}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error during GPT-4 post-processing: {e}")
        return f"Error during post-processing: {e}"

# --- Pyannote.ai Helper Functions ---
def upload_to_pyannote_temp(local_filepath, filename_ext):
    """Uploads a local file to Pyannote's temporary storage."""
    if not PYANNOTE_API_KEY:
        raise ValueError("Pyannote API Key not configured.")

    # Create a unique temporary media URL path
    media_path = f"media://{uuid.uuid4()}/conversation.{filename_ext}"
    print(f"Requesting pre-signed URL for Pyannote: {media_path}")

    # 1. Get pre-signed URL
    try:
        create_body = {"url": media_path}
        response = requests.post(PYANNOTE_MEDIA_URL, json=create_body, headers=PYANNOTE_HEADERS)
        response.raise_for_status()
        data = response.json()
        presigned_put_url = data.get("url")
        if not presigned_put_url:
             raise ValueError("Failed to get pre-signed PUT URL from Pyannote.")
        print("Obtained pre-signed URL.")
    except requests.exceptions.RequestException as e:
        print(f"Error getting Pyannote pre-signed URL: {e}")
        print(f"Response status: {e.response.status_code if e.response else 'N/A'}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        raise ConnectionError(f"Failed to get Pyannote pre-signed URL: {e}") from e

    # 2. Upload file to pre-signed URL
    try:
        print(f"Uploading {local_filepath} to Pyannote...")
        with open(local_filepath, "rb") as input_file:
            # Determine content type (optional but good practice)
            content_type, _ = mimetypes.guess_type(local_filepath)
            upload_headers = {}
            if content_type:
                upload_headers['Content-Type'] = content_type

            upload_response = requests.put(presigned_put_url, data=input_file, headers=upload_headers)
            upload_response.raise_for_status()
        print("Upload to Pyannote temporary storage successful.")
        return media_path # Return the media:// URL for the job request
    except requests.exceptions.RequestException as e:
        print(f"Error uploading file to Pyannote pre-signed URL: {e}")
        print(f"Response status: {e.response.status_code if e.response else 'N/A'}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        raise ConnectionError(f"Failed to upload to Pyannote: {e}") from e
    except Exception as e:
        print(f"Error reading local file for Pyannote upload: {e}")
        raise

def start_pyannote_diarization(media_url, webhook_url=None):
    """Starts a Pyannote diarization job using a temporary media URL."""
    if not PYANNOTE_API_KEY:
        raise ValueError("Pyannote API Key not configured.")

    print(f"Starting Pyannote diarization job for: {media_url}")
    # Create job body with optional webhook
    job_body = {
        "url": media_url
    }
    
    # Add webhook URL if provided
    if webhook_url:
        job_body["webhook"] = webhook_url
        print(f"Using webhook URL: {webhook_url}")
    
    try:
        response = requests.post(PYANNOTE_DIARIZE_URL, json=job_body, headers=PYANNOTE_HEADERS)
        response.raise_for_status()
        job_data = response.json()
        print(f"Pyannote job created: {job_data}")
        return job_data.get("jobId"), job_data.get("status", "unknown")
    except requests.exceptions.RequestException as e:
        print(f"Error starting Pyannote diarization job: {e}")
        print(f"Response status: {e.response.status_code if e.response else 'N/A'}")
        print(f"Response text: {e.response.text if e.response else 'N/A'}")
        raise ConnectionError(f"Failed to start Pyannote job: {e}") from e


# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)


@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    start_time = time.time()
    num_chunks_created = 1
    pyannote_job_id = None
    pyannote_status = None
    # Define webhook URL base from env var
    public_webhook_base = os.getenv("PUBLIC_WEBHOOK_URL_BASE")
    webhook_url_for_pyannote = None

    # Check API Keys
    if not openai_client.api_key:
         return jsonify({"error": "Server configuration error: OpenAI API key not set."}), 500

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        # --- Get Form Data ---
        user_prompt = request.form.get('prompt', '')
        dictionary_terms = request.form.get('dictionary', '')
        do_post_process = request.form.get('post_process') == 'on'
        # Get the new GPT-4.1 post-processing prompt
        gpt4_post_process_prompt = request.form.get('post_process_prompt', '')
        # Check if diarization is requested
        request_diarization = request.form.get('request_diarization') == 'on'

        # --- Prepare File ---
        original_filename = file.filename
        file_ext = get_file_extension(original_filename)
        unique_id = uuid.uuid4()
        filename = f"{unique_id}_{original_filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        chunk_files = []  # Ensure chunk_files is initialized here

        try:
            file.save(filepath)
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"Received file: {filename}, Size: {file_size_mb:.2f} MB")

            # --- Optional: Pyannote.ai Diarization Request ---
            if request_diarization:
                if not PYANNOTE_API_KEY:
                    print("Diarization requested but PYANNOTE_API_KEY is not set. Skipping.")
                    pyannote_status = "skipped_no_key"
                elif not public_webhook_base:
                    # Check for webhook base URL
                    print("Diarization requested but PUBLIC_WEBHOOK_URL_BASE env var is not set. Skipping.")
                    pyannote_status = "skipped_no_webhook_url"
                else:
                    try:
                        # Construct the full webhook URL
                        webhook_url_for_pyannote = f"{public_webhook_base.rstrip('/')}/webhook/pyannote"
                        print(f"Using Pyannote webhook URL: {webhook_url_for_pyannote}")

                        pyannote_media_url = upload_to_pyannote_temp(filepath, file_ext)
                        # Pass webhook URL to start_pyannote_diarization
                        pyannote_job_id, pyannote_status = start_pyannote_diarization(
                            pyannote_media_url, webhook_url_for_pyannote
                        )
                    except Exception as pyannote_e:
                        print(f"Error during Pyannote processing: {pyannote_e}")
                        pyannote_status = f"error: {str(pyannote_e)}"

            # --- OpenAI Transcription (Chunking if needed) ---
            effective_prompt = user_prompt
            if dictionary_terms:
                 effective_prompt = (effective_prompt + "\n\n" if effective_prompt else "") + \
                                   "Ensure these terms are spelled correctly: " + dictionary_terms
            print(f"Effective Prompt for Whisper: {effective_prompt[:200]}...")

            full_transcription = ""  # Initialize as empty string
            last_chunk_transcript = ""

            if file_size_mb > MAX_FILE_SIZE_MB:
                # (Chunking logic starts here)
                print(f"File size ({file_size_mb:.2f}MB) exceeds limit ({MAX_FILE_SIZE_MB}MB). Chunking...")
                audio = AudioSegment.from_file(filepath)
                duration_ms = len(audio)
                chunk_duration_ms = 15 * 60 * 1000
                num_chunks_created = ceil(duration_ms / chunk_duration_ms)
                print(f"Splitting into {num_chunks_created} chunks...")

                for i in range(num_chunks_created):
                    start_ms = i * chunk_duration_ms
                    end_ms = min((i + 1) * chunk_duration_ms, duration_ms)
                    chunk = audio[start_ms:end_ms]

                    # Always export chunks as MP3 for robust compatibility
                    chunk_format = "mp3"
                    chunk_filename = f"{unique_id}_chunk_{i+1}.{chunk_format}"
                    chunk_filepath = os.path.join(app.config['UPLOAD_FOLDER'], chunk_filename)

                    try:
                        print(f"Exporting chunk {i+1}/{num_chunks_created} to {chunk_filepath} (format: {chunk_format})")
                        chunk.export(chunk_filepath, format=chunk_format)
                        chunk_files.append(chunk_filepath)  # Add AFTER successful export

                        # Context prompt logic
                        chunk_prompt = effective_prompt
                        # Could add additional context from previous chunks here if needed

                        print(f"==> Transcribing chunk {i+1} with prompt: {'Yes' if chunk_prompt else 'No'}")
                        # Call the updated transcribe_chunk
                        transcript_part = transcribe_chunk(chunk_filepath, chunk_prompt)

                        # Check if transcript_part is valid
                        if transcript_part and isinstance(transcript_part, str):
                            print(f"==> Appending chunk {i+1} transcript (length {len(transcript_part)}).")
                            full_transcription += transcript_part.strip() + " "  # Append and add space
                            last_chunk_transcript = transcript_part  # Update context for next chunk
                        else:
                            print(f"==> WARNING: Chunk {i+1} returned empty or invalid transcript: {transcript_part}")
                            # Decide: continue with empty part, or raise error? For now, let's just log.

                    except Exception as chunk_e:
                        # Handle errors during export or transcription of THIS chunk
                        print(f"!!! Error processing chunk {i+1}: {chunk_e}")
                        # Re-raise to stop the whole process
                        raise

                    finally:
                        # Cleanup chunk file even if transcription failed
                        if os.path.exists(chunk_filepath):
                            try:
                                os.remove(chunk_filepath)
                                print(f"<-- Removed chunk file: {chunk_filepath}")
                            except OSError as e:
                                print(f"Error removing chunk file {chunk_filepath}: {e}")

                # Trim trailing space after the loop
                full_transcription = full_transcription.strip()
                print(f"==> Final combined transcription length: {len(full_transcription)}")

            else:
                # Single file transcription
                print(f"Transcribing single file with prompt: {'Yes' if effective_prompt else 'No'}")
                full_transcription = transcribe_chunk(filepath, effective_prompt)
                print(f"Single file transcript length: {len(full_transcription)}")
                full_transcription = full_transcription.strip() if full_transcription else ""

            # --- Optional Post-processing (using specific prompt now) ---
            post_processed_text = None
            if do_post_process and full_transcription:
                print("Performing post-processing with GPT-4 Turbo...")
                # Pass the dictionary terms AND the specific GPT-4 prompt
                post_processed_text = post_process_text(
                    full_transcription,
                    dictionary_terms, # Pass dictionary for potential use in system prompt
                    gpt4_post_process_prompt # Pass the dedicated prompt
                )
                print("Post-processing complete.")
            elif do_post_process and not full_transcription:
                 print("Skipping post-processing because transcription was empty.")

            end_time = time.time()
            processing_time = end_time - start_time

            # --- Return Results ---
            return jsonify({
                "transcription": full_transcription,
                "post_processed_transcription": post_processed_text,
                "processing_time": f"{processing_time:.2f}",
                "chunks_created": num_chunks_created,
                "pyannote_job_id": pyannote_job_id,
                "pyannote_status": pyannote_status,
                "pyannote_webhook_used": webhook_url_for_pyannote  # Inform user which URL was sent
            })

        except Exception as e:
            end_time = time.time()
            processing_time = end_time - start_time
            print(f"An error occurred after {processing_time:.2f} seconds: {e}")
            # Cleanup chunks on error
            for chunk_file in chunk_files:
                 if os.path.exists(chunk_file):
                     try:
                         os.remove(chunk_file)
                         print(f"<-- Cleaned up chunk file on error: {chunk_file}")
                     except OSError as remove_e:
                         print(f"Error removing chunk file during error cleanup {chunk_file}: {remove_e}")
            return jsonify({"error": f"An error occurred during processing: {str(e)}"}), 500
        finally:
            # Clean up original file
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    print(f"<-- Removed original file: {filepath}")
                except OSError as e:
                    print(f"Error removing original file {filepath}: {e}")
            # Cleanup any remaining chunk files
            for chunk_f in chunk_files:
                 if os.path.exists(chunk_f):
                     try:
                         os.remove(chunk_f)
                         print(f"<-- Cleaned up leftover chunk file: {chunk_f}")
                     except OSError as remove_e:
                         print(f"Error removing chunk file during final cleanup {chunk_f}: {remove_e}")

    else:
        return jsonify({"error": "File type not allowed"}), 400

if __name__ == '__main__':
    # Make sure to set FLASK_ENV=development for debug mode if needed outside Docker
    app.run(host='0.0.0.0', port=5000, debug=False)