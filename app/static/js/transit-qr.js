/**
 * Client-side script for Transit Partner QR Generator Hub.
 */

document.addEventListener("DOMContentLoaded", () => {
  const providerSelect = document.getElementById("provider-select");
  const hubInput = document.getElementById("hub-name-input");
  const btnGenerate = document.getElementById("btn-generate-qr");

  const previewTitle = document.getElementById("preview-hub-title");
  const previewSubtitle = document.getElementById("preview-provider-subtitle");
  const svgContainer = document.getElementById("qr-svg-container");
  const testLink = document.getElementById("qr-test-link");
  const btnCopy = document.getElementById("btn-copy-url");

  let currentDestinationUrl = "";

  async function fetchQR() {
    const provider = providerSelect.value.trim() || "AutoUnion";
    const hub = hubInput.value.trim() || "GeneralTerminal";

    try {
      const resp = await fetch(`/api/guest/transit/qr-config?provider=${encodeURIComponent(provider)}&hub=${encodeURIComponent(hub)}`);
      if (!resp.ok) throw new Error("Could not generate QR configuration.");

      const data = await resp.json();
      currentDestinationUrl = data.destination_url;

      previewTitle.textContent = data.hub_name;
      previewSubtitle.textContent = data.provider_name;
      svgContainer.innerHTML = data.qr_svg;
      testLink.href = data.destination_url;

      btnCopy.onclick = () => {
        navigator.clipboard.writeText(currentDestinationUrl);
        btnCopy.textContent = "✓ Copied!";
        setTimeout(() => (btnCopy.textContent = "Copy Destination URL"), 2000);
      };
    } catch (err) {
      svgContainer.innerHTML = `<span style="color:#ef4444; font-size:0.8rem;">Generation error</span>`;
    }
  }

  if (btnGenerate) {
    btnGenerate.addEventListener("click", fetchQR);
  }

  // Initial load
  fetchQR();
});
