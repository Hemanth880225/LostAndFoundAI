/**
 * Client-side script for Guest Case Tracking, Masked Messaging, Handover Confirmation, and AI Matching.
 */

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("guest-case-view");
  if (!container) return;

  const caseRef = container.getAttribute("data-case-ref");
  let secretKey = container.getAttribute("data-initial-key");

  const authBox = document.getElementById("auth-box");
  const caseContent = document.getElementById("case-content");
  const inputSecretKey = document.getElementById("input-secret-key");
  const btnUnlock = document.getElementById("btn-unlock-case");

  // Facts & Details
  const displayStatus = document.getElementById("display-status");
  const displaySecret = document.getElementById("display-secret-key");
  const factName = document.getElementById("fact-name");
  const factCategory = document.getElementById("fact-category");
  const factJourney = document.getElementById("fact-journey");
  const factDate = document.getElementById("fact-date");
  const factPickup = document.getElementById("fact-pickup");
  const factDropoff = document.getElementById("fact-dropoff");
  const factDesc = document.getElementById("fact-desc");
  const factPrivateContents = document.getElementById("fact-private-contents");
  const factDistinctiveMarks = document.getElementById("fact-distinctive-marks");

  // Images
  const mainImage = document.getElementById("case-main-image");
  const gallery = document.getElementById("case-gallery");

  // Messages
  const messagesList = document.getElementById("messages-list");
  const msgForm = document.getElementById("msg-form");
  const inputMsgText = document.getElementById("input-msg-text");

  // Handover
  const handoverBadge = document.getElementById("handover-status-badge");
  const activeHandoverBox = document.getElementById("active-handover-box");
  const handoverCodeDisplay = document.getElementById("handover-code-display");
  const handoverLocationText = document.getElementById("handover-location-text");
  const inputConfirmCode = document.getElementById("input-confirm-code");
  const btnConfirmHandover = document.getElementById("btn-confirm-handover");

  // Reward Linking
  const rewardLinkedStatus = document.getElementById("reward-linked-status");
  const rewardLinkForm = document.getElementById("reward-link-form");
  const linkedEmailDisplay = document.getElementById("linked-email-display");
  const inputLinkEmail = document.getElementById("input-link-email");
  const btnLinkEmail = document.getElementById("btn-link-email");

  // Matches
  const matchesContainer = document.getElementById("matches-container");
  const btnRefreshMatches = document.getElementById("btn-refresh-matches");

  let currentCaseData = null;

  // Check URL query param for key if not in dataset
  if (!secretKey) {
    const urlParams = new URLSearchParams(window.location.search);
    secretKey = urlParams.get("key");
  }

  if (secretKey) {
    loadCase(secretKey);
  } else {
    authBox.style.display = "block";
  }

  if (btnUnlock) {
    btnUnlock.addEventListener("click", () => {
      const entered = inputSecretKey.value.trim();
      if (entered) {
        secretKey = entered;
        loadCase(secretKey);
      }
    });
  }

  async function loadCase(key) {
    try {
      const resp = await fetch(`/api/guest/cases/${caseRef}?key=${encodeURIComponent(key)}`);
      if (!resp.ok) {
        authBox.style.display = "block";
        caseContent.style.display = "none";
        alert("Invalid secret key or case reference.");
        return;
      }

      const data = await resp.json();
      currentCaseData = data;
      authBox.style.display = "none";
      caseContent.style.display = "block";

      renderCaseDetails(data);
      loadMatches(data.report_id);
    } catch (err) {
      console.error("Failed to load case:", err);
    }
  }

  function renderCaseDetails(data) {
    displayStatus.textContent = data.report_status.toUpperCase();
    displaySecret.textContent = secretKey;

    factName.textContent = data.item_name;
    factCategory.textContent = data.category;
    factJourney.textContent = data.journey_type ? data.journey_type.replace(/_/g, " ").toUpperCase() : "Transit";
    factDate.textContent = data.event_date;
    factPickup.textContent = data.pickup_location || "Not specified";
    factDropoff.textContent = data.dropoff_location || "Not specified";
    factDesc.textContent = data.public_description;

    factPrivateContents.textContent = data.private_contents || "None recorded";
    factDistinctiveMarks.textContent = data.distinctive_marks || "None recorded";

    // Render gallery
    if (data.images && data.images.length > 0) {
      mainImage.innerHTML = `<img src="${data.images[0]}" alt="${data.item_name}">`;
      gallery.innerHTML = "";
      data.images.forEach((imgUrl) => {
        const thumb = document.createElement("div");
        thumb.className = "gallery-thumb";
        thumb.innerHTML = `<img src="${imgUrl}" alt="Thumbnail">`;
        thumb.onclick = () => {
          mainImage.innerHTML = `<img src="${imgUrl}" alt="${data.item_name}">`;
        };
        gallery.appendChild(thumb);
      });
    }

    // Render Handover
    if (data.active_handover) {
      handoverBadge.textContent = data.active_handover.status.toUpperCase();
      activeHandoverBox.style.display = "block";
      handoverCodeDisplay.textContent = data.active_handover.handover_code;
      handoverLocationText.textContent = `Agreed Location: ${data.active_handover.agreed_location_name}`;
    }

    // Render Reward Link status
    if (data.linked_account_email) {
      rewardLinkedStatus.style.display = "block";
      rewardLinkForm.style.display = "none";
      linkedEmailDisplay.textContent = data.linked_account_email;
    }

    // Render Messages
    renderMessages(data.messages || []);
  }

  function renderMessages(msgs) {
    messagesList.innerHTML = "";
    if (msgs.length === 0) {
      messagesList.innerHTML = `<div class="msg-bubble msg-system">No messages yet. Send a message to coordinate.</div>`;
      return;
    }

    msgs.forEach((m) => {
      const bubble = document.createElement("div");
      bubble.className = `msg-bubble msg-${m.sender_role}`;
      bubble.textContent = m.message_text;
      messagesList.appendChild(bubble);
    });
    messagesList.scrollTop = messagesList.scrollHeight;
  }

  // Send message
  if (msgForm) {
    msgForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = inputMsgText.value.trim();
      if (!text) return;

      try {
        const resp = await fetch(`/api/guest/cases/${caseRef}/messages?key=${encodeURIComponent(secretKey)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_text: text }),
        });

        if (resp.ok) {
          inputMsgText.value = "";
          const newMsg = await resp.json();
          if (currentCaseData) {
            currentCaseData.messages.push(newMsg);
            renderMessages(currentCaseData.messages);
          }
        }
      } catch (err) {
        alert("Failed to send message: " + err.message);
      }
    });
  }

  // Confirm Handover
  if (btnConfirmHandover) {
    btnConfirmHandover.addEventListener("click", async () => {
      const code = inputConfirmCode.value.trim();
      if (!code) {
        alert("Please enter the handover verification code.");
        return;
      }

      btnConfirmHandover.disabled = true;
      try {
        const role = currentCaseData && currentCaseData.guest_role === "passenger" ? "claimant" : "finder";
        const resp = await fetch(`/api/guest/cases/${caseRef}/handover/confirm?key=${encodeURIComponent(secretKey)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ handover_code: code, confirmed_by: role }),
        });

        const res = await resp.json();
        if (!resp.ok) {
          alert(res.detail || "Could not confirm handover code.");
        } else {
          alert("🎉 " + res.message);
          loadCase(secretKey);
        }
      } catch (err) {
        alert("Error confirming handover: " + err.message);
      } finally {
        btnConfirmHandover.disabled = false;
      }
    });
  }

  // Link Email for Rewards
  if (btnLinkEmail) {
    btnLinkEmail.addEventListener("click", async () => {
      const email = inputLinkEmail.value.trim();
      if (!email || !email.includes("@")) {
        alert("Please enter a valid email address.");
        return;
      }

      try {
        const resp = await fetch(`/api/guest/cases/${caseRef}/link-account?key=${encodeURIComponent(secretKey)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email }),
        });

        const res = await resp.json();
        if (resp.ok) {
          alert("✓ " + res.message);
          rewardLinkedStatus.style.display = "block";
          rewardLinkForm.style.display = "none";
          linkedEmailDisplay.textContent = res.linked_account_email;
        } else {
          alert(res.detail || "Could not link account.");
        }
      } catch (err) {
        alert("Failed to link account: " + err.message);
      }
    });
  }

  // Load Matches
  async function loadMatches(reportId) {
    matchesContainer.innerHTML = `<div style="color:#94a3b8; font-size:0.85rem; text-align:center; padding:16px;">Scanning reports…</div>`;
    try {
      const resp = await fetch(`/api/guest/matches/${reportId}?limit=6`);
      if (!resp.ok) {
        matchesContainer.innerHTML = `<div style="color:#94a3b8; font-size:0.85rem; text-align:center; padding:16px;">No potential transit matches found yet.</div>`;
        return;
      }

      const matches = await resp.json();
      if (matches.length === 0) {
        matchesContainer.innerHTML = `<div style="color:#94a3b8; font-size:0.85rem; text-align:center; padding:16px;">No candidate matches meeting confidence threshold yet. Check back later!</div>`;
        return;
      }

      matchesContainer.innerHTML = "";
      matches.forEach((m) => {
        const card = document.createElement("div");
        card.style.cssText = "background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px; display:flex; justify-content:space-between; align-items:center;";

        card.innerHTML = `
          <div>
            <strong style="font-size:0.92rem; color:#0f172a;">${m.item_name}</strong>
            <small style="display:block; color:#64748b; font-size:0.78rem;">📍 ${m.location_text} • 🗓️ ${m.event_date}</small>
            <span style="font-size:0.75rem; color:#4338ca; display:block; margin-top:2px;">ℹ️ ${m.explanation}</span>
          </div>
          <div style="text-align:right;">
            <span style="font-weight:800; font-size:1.1rem; color:#2563eb;">${m.score}%</span>
            <small style="display:block; font-size:0.7rem; color:#94a3b8;">Match</small>
            <a href="/reports/${m.candidate_report_id}" target="_blank" style="font-size:0.75rem; color:#2563eb; font-weight:700;">View →</a>
          </div>
        `;
        matchesContainer.appendChild(card);
      });
    } catch (err) {
      matchesContainer.innerHTML = `<div style="color:#ef4444; font-size:0.85rem; text-align:center; padding:16px;">Error loading matches.</div>`;
    }
  }

  if (btnRefreshMatches) {
    btnRefreshMatches.addEventListener("click", () => {
      if (currentCaseData) loadMatches(currentCaseData.report_id);
    });
  }
});
