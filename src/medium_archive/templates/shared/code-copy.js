(function () {
  function init() {
    var article = document.querySelector(".post");
    var template = document.querySelector(".code-copy-template");
    var status = document.querySelector(".code-copy-status");
    if (!article || !template || !status || !template.content) return;
    if (!navigator.clipboard || !navigator.clipboard.writeText) return;
    Array.prototype.forEach.call(article.querySelectorAll("pre"), function (pre) {
      if (pre.closest(".code-block")) return;
      var block = document.createElement("div");
      block.className = "code-block";
      pre.parentNode.insertBefore(block, pre);
      block.appendChild(pre);
      var button = template.content.firstElementChild.cloneNode(true);
      block.appendChild(button);
      var icons = button.querySelectorAll("svg");
      var timer;
      function show(state, label) {
        icons.forEach(function (icon) {
          icon.toggleAttribute("hidden", icon.dataset.copyState !== state);
        });
        button.title = label;
        button.setAttribute("aria-label", label);
      }
      function announce(text) {
        status.textContent = "";
        status.textContent = text;
      }
      button.addEventListener("click", function () {
        var text = pre.textContent.replace(/\n$/, "");
        navigator.clipboard.writeText(text).then(function () {
          show("copied", "Copied");
          announce("Copied to clipboard");
          clearTimeout(timer);
          timer = setTimeout(function () { show("ready", "Copy code"); }, 1500);
        }, function () {
          announce("Copy failed");
        });
      });
    });
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
