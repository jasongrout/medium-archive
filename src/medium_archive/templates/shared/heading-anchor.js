(function () {
  function init() {
    var article = document.querySelector(".post");
    var template = document.querySelector(".heading-anchor-template");
    if (!article || !template || !template.content) return;
    var headings = article.querySelectorAll(
      "h1[id], h2[id], h3[id], h4[id], h5[id], h6[id]");
    Array.prototype.forEach.call(headings, function (heading) {
      if (heading.querySelector(".heading-anchor")) return;
      var link = template.content.firstElementChild.cloneNode(true);
      link.setAttribute("href", "#" + heading.id);
      heading.appendChild(link);
    });
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
