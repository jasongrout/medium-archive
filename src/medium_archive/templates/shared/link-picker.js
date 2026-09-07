(function () {
  var root = document.documentElement;
  var picker = document.querySelector(".link-picker");
  if (!picker) return;
  var select = picker.querySelector("select");
  var options = select.options;
  function apply(choice) {
    select.value = choice;
    if (choice === "ink") root.removeAttribute("data-link");
    else root.setAttribute("data-link", choice);
    try {
      if (choice === "ink") localStorage.removeItem("link");
      else localStorage.setItem("link", choice);
    } catch (e) {}
  }
  select.addEventListener("change", function () {
    apply(select.value);
  });
  var stored = root.getAttribute("data-link");
  var known = false;
  for (var i = 0; i < options.length; i++) {
    if (options[i].value === stored) known = true;
  }
  apply(known ? stored : "ink");
  picker.hidden = false;
})();
