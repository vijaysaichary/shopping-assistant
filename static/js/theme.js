(function () {
  const root = document.documentElement;
  const stored = localStorage.getItem("theme");
  if (stored) root.setAttribute("data-theme", stored);

  window.toggleTheme = function () {
    const current = root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    document.querySelectorAll("[data-theme-icon]").forEach((el) => {
      el.textContent = next === "dark" ? "☀️" : "🌙";
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    const current = root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.querySelectorAll("[data-theme-icon]").forEach((el) => {
      el.textContent = current === "dark" ? "☀️" : "🌙";
    });
  });
})();
