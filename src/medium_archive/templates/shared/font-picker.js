(function () {
  var root = document.documentElement;
  var picker = document.querySelector(".font-picker");
  if (!picker) return;
  var select = picker.querySelector("select");
  var options = select.options;
  function apply(choice) {
    select.value = choice;
    select.style.fontFamily = options[select.selectedIndex].style.fontFamily;
    if (choice === "source-serif") root.removeAttribute("data-font");
    else root.setAttribute("data-font", choice);
    try {
      if (choice === "source-serif") localStorage.removeItem("font");
      else localStorage.setItem("font", choice);
    } catch (e) {}
  }
  select.addEventListener("change", function () {
    apply(select.value);
  });
  var stored = root.getAttribute("data-font");
  var known = false;
  for (var i = 0; i < options.length; i++) {
    if (options[i].value === stored) known = true;
  }
  apply(known ? stored : "source-serif");
  picker.hidden = false;
})();
