// --- Get Element References (Add new ones) ---
const form = document.getElementById("upload-form");
const statusDiv = document.getElementById("status");
const resultsDiv = document.getElementById("results");
const transcriptionOutput = document.getElementById("transcription-output");
const postProcessedOutput = document.getElementById("post-processed-output");
const postProcessedSection = document.getElementById("post-processed-section");
const submitButton = document.getElementById("submit-button");
const processingInfoDiv = document.getElementById("processing-info");
const timeTakenSpan = document.getElementById("time-taken");
const chunkCountSpan = document.getElementById("chunk-count");
const copyRawButton = document.getElementById("copy-raw-button");
const copyPostButton = document.getElementById("copy-post-button");
// Pyannote elements
const pyannoteInfoDiv = document.getElementById("pyannote-info");
const pyannoteStatusSpan = document.getElementById("pyannote-status");
const pyannoteJobIdSpan = document.getElementById("pyannote-job-id");

// --- Clipboard Function (remains the same) ---
async function copyToClipboard(elementId, buttonElement) {
  const textToCopy = document.getElementById(elementId)?.textContent;
  if (!textToCopy || textToCopy === "---") {
    alert("Nothing to copy!");
    return;
  }
  try {
    await navigator.clipboard.writeText(textToCopy);
    const originalText = buttonElement.textContent;
    buttonElement.textContent = "Copied!";
    buttonElement.style.backgroundColor = "#28a745";
    setTimeout(() => {
      buttonElement.textContent = originalText;
      buttonElement.style.backgroundColor = "";
    }, 1500);
  } catch (err) {
    console.error("Failed to copy text: ", err);
    alert("Failed to copy text. Check browser permissions or console.");
  }
}

// --- Add Event Listeners for Copy Buttons (remains the same) ---
copyRawButton.addEventListener("click", () => {
  copyToClipboard(copyRawButton.dataset.target, copyRawButton);
});
copyPostButton.addEventListener("click", () => {
  copyToClipboard(copyPostButton.dataset.target, copyPostButton);
});

// --- Form Submission Handler (Updated) ---
form.addEventListener("submit", async (event) => {
  event.preventDefault();

  // Reset UI
  statusDiv.textContent = "Uploading and processing... Please wait.";
  statusDiv.style.color = "orange";
  resultsDiv.style.display = "none"; // Hide results initially
  transcriptionOutput.textContent = "---";
  postProcessedOutput.textContent = "---";
  postProcessedSection.style.display = "none";
  processingInfoDiv.style.display = "none";
  pyannoteInfoDiv.style.display = "none"; // Hide Pyannote info initially
  pyannoteStatusSpan.textContent = "---";
  pyannoteJobIdSpan.textContent = "---";
  timeTakenSpan.textContent = "---";
  chunkCountSpan.textContent = "---";
  submitButton.disabled = true;

  const formData = new FormData(form);

  try {
    const response = await fetch("/transcribe", {
      method: "POST",
      body: formData,
    });

    const result = await response.json();
    resultsDiv.style.display = "block"; // Show results container

    if (response.ok) {
      statusDiv.textContent = "Processing complete!";
      statusDiv.style.color = "green";

      // Display OpenAI results
      transcriptionOutput.textContent =
        result.transcription || "(Transcription was empty)";
      timeTakenSpan.textContent = result.processing_time || "N/A";
      chunkCountSpan.textContent = result.chunks_created || "N/A";
      processingInfoDiv.style.display = "block"; // Show general processing info

      // Display Post-processing result if available
      if (
        result.post_processed_transcription !== null &&
        result.post_processed_transcription !== undefined
      ) {
        postProcessedOutput.textContent =
          result.post_processed_transcription ||
          "(Post-processing resulted in empty text)";
        postProcessedSection.style.display = "block";
      } else {
        postProcessedSection.style.display = "none";
        postProcessedOutput.textContent = "---";
      }

      // Display Pyannote Job Info if available
      if (result.pyannote_status) {
        pyannoteStatusSpan.textContent = result.pyannote_status;
        pyannoteJobIdSpan.textContent = result.pyannote_job_id || "N/A";
        // Handle specific statuses text if desired
        if (result.pyannote_status === "skipped_config") {
          pyannoteStatusSpan.textContent = "Skipped (API Key Missing)";
          pyannoteJobIdSpan.textContent = "N/A";
        } else if (result.pyannote_status.startsWith("error:")) {
          pyannoteStatusSpan.textContent = `Error (${result.pyannote_status.substring(
            6
          )})`; // Show error message part
          pyannoteJobIdSpan.textContent = "N/A";
        }
        pyannoteInfoDiv.style.display = "block"; // Show Pyannote section
      } else {
        pyannoteInfoDiv.style.display = "none"; // Hide if no Pyannote status
      }
    } else {
      statusDiv.textContent = `Error: ${
        result.error || "Unknown server error"
      }`;
      statusDiv.style.color = "red";
      console.error("Server Error:", result.error);
      resultsDiv.style.display = "none"; // Keep results hidden on error
    }
  } catch (error) {
    statusDiv.textContent = `Network or client-side error: ${error.message}`;
    statusDiv.style.color = "red";
    console.error("Fetch Error:", error);
    resultsDiv.style.display = "none"; // Keep results hidden on error
  } finally {
    submitButton.disabled = false;
  }
});
