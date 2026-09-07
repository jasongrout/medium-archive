(function () {
  var root = document.documentElement;
  var picker = document.querySelector(".theme-picker");
  if (!picker) return;
  var button = picker.querySelector("button");
  var icons = button.querySelectorAll("svg");
  var order = ["light", "dark", "system"];
  var current;
  function apply(choice) {
    current = choice;
    if (choice === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
    try {
      if (choice === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", choice);
    } catch (e) {}
    icons.forEach(function (icon) {
      icon.style.display = icon.dataset.setTheme === choice ? "" : "none";
    });
    var next = order[(order.indexOf(choice) + 1) % order.length];
    var label = "Color scheme: " + choice + " (switch to " + next + ")";
    button.title = label;
    button.setAttribute("aria-label", label);
  }
  button.addEventListener("click", function () {
    apply(order[(order.indexOf(current) + 1) % order.length]);
  });
  apply(root.getAttribute("data-theme") || "system");
  picker.hidden = false;
})();
