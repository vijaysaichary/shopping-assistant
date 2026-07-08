document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.target);
      if (!input) return;
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      btn.textContent = showing ? "👁️" : "🙈";
    });
  });

  const passwordInput = document.getElementById("password");
  const strengthMeter = document.getElementById("strengthMeter");
  const strengthLabel = document.getElementById("strengthLabel");

  if (passwordInput && strengthMeter) {
    const bars = strengthMeter.querySelectorAll("span");
    const colors = ["#dc2626", "#d97706", "#eab308", "#16a34a"];
    const labels = ["Weak", "Fair", "Good", "Strong"];

    passwordInput.addEventListener("input", () => {
      const value = passwordInput.value;
      let score = 0;
      if (value.length >= 8) score++;
      if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score++;
      if (/\d/.test(value)) score++;
      if (/[^A-Za-z0-9]/.test(value)) score++;

      bars.forEach((bar, i) => {
        bar.style.background = i < score ? colors[Math.max(score - 1, 0)] : "var(--border)";
      });
      strengthLabel.textContent = value ? labels[Math.max(score - 1, 0)] : "";
    });
  }
});
