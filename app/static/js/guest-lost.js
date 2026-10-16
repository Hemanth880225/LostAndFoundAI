/**
 * Client-side script for Passenger Lost Item Report in Transit.
 */

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("guest-lost-form");
  const fileInput = document.getElementById("file-input");
  const uploadBox = document.getElementById("upload-box");
  const previewGrid = document.getElementById("image-preview-grid");
  const journeyButtons = document.querySelectorAll(".journey-btn");
  const journeyTypeInput = document.getElementById("journey-type");
  const contactValInput = document.getElementById("contact-val");
  const contactMethodInput = document.getElementById("contact-method");
  const formError = document.getElementById("form-error");
  const btnSubmit = document.getElementById("btn-submit");

  // Receipt Modal
  const receiptModal = document.getElementById("receipt-modal");
  const modalCaseRef = document.getElementById("modal-case-ref");
  const modalSecretPill = document.getElementById("modal-secret-pill");
  const modalTrackBtn = document.getElementById("modal-track-btn");
  const modalCopyBtn = document.getElementById("modal-copy-btn");

  let selectedFiles = [];

  if (uploadBox && fileInput) {
    uploadBox.addEventListener("click", () => fileInput.click());

    uploadBox.addEventListener("dragover", (e) => {
      e.preventDefault();
      uploadBox.classList.add("dragover");
    });

    uploadBox.addEventListener("dragleave", () => {
      uploadBox.classList.remove("dragover");
    });

    uploadBox.addEventListener("drop", (e) => {
      e.preventDefault();
      uploadBox.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleNewFiles(Array.from(e.dataTransfer.files));
      }
    });

    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleNewFiles(Array.from(fileInput.files));
      }
    });
  }

  function handleNewFiles(files) {
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      if (selectedFiles.length >= 10) break;
      selectedFiles.push(file);
    }
    renderPreviews();
  }

  function renderPreviews() {
    previewGrid.innerHTML = "";
    selectedFiles.forEach((file, index) => {
      const card = document.createElement("div");
      card.className = "preview-card";

      const thumb = document.createElement("div");
      thumb.className = "preview-card-thumb";

      const img = document.createElement("img");
      const reader = new FileReader();
      reader.onload = (e) => (img.src = e.target.result);
      reader.readAsDataURL(file);
      thumb.appendChild(img);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "preview-card-remove";
      removeBtn.innerHTML = "×";
      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        selectedFiles.splice(index, 1);
        renderPreviews();
      });
      card.appendChild(removeBtn);

      const meta = document.createElement("div");
      meta.className = "preview-card-meta";
      meta.innerHTML = `<span class="preview-card-name">${file.name}</span>
                        <span class="preview-card-size">${(file.size / 1024).toFixed(1)} KB</span>`;

      card.appendChild(thumb);
      card.appendChild(meta);
      previewGrid.appendChild(card);
    });
  }

  journeyButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      journeyButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      journeyTypeInput.value = btn.getAttribute("data-type");
    });
  });

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      formError.style.display = "none";
      btnSubmit.disabled = true;
      btnSubmit.textContent = "Registering Report…";

      try {
        const formData = new FormData(form);
        selectedFiles.forEach((f) => formData.append("files", f));

        const cVal = contactValInput ? contactValInput.value.trim() : "";
        if (cVal) {
          formData.set("contact_method", cVal.includes("@") ? "email" : "phone");
          formData.set("contact_value", cVal);
        }

        const resp = await fetch("/api/guest/lost", {
          method: "POST",
          body: formData,
        });

        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          throw new Error(errData.detail || "Could not submit report.");
        }

        const receipt = await resp.json();

        modalCaseRef.textContent = receipt.case_reference;
        modalSecretPill.textContent = `Secret Key: ${receipt.secret_key}`;
        modalTrackBtn.href = receipt.tracking_url;

        modalCopyBtn.onclick = () => {
          navigator.clipboard.writeText(
            `Case: ${receipt.case_reference}\nSecret Key: ${receipt.secret_key}\nTracking URL: ${receipt.tracking_url}`
          );
          modalCopyBtn.textContent = "✓ Copied to Clipboard!";
          setTimeout(() => (modalCopyBtn.textContent = "Copy Reference & Secret Key"), 2500);
        };

        receiptModal.style.display = "flex";
      } catch (err) {
        formError.textContent = err.message;
        formError.style.display = "block";
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = "Register Lost Item Report";
      }
    });
  }
});
