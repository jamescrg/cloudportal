// A small eye button inside each password field on the sign-in pages, to
// show what was typed and hide it again. The fields are drawn by the site's
// form template, so the button is added here rather than in the markup.
(function () {
  document.querySelectorAll(".account-form input[type=password]").forEach(function (input) {
    var wrap = document.createElement("div");
    wrap.className = "password-reveal";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "password-reveal-button";
    wrap.appendChild(button);

    function show(visible) {
      input.type = visible ? "text" : "password";
      button.innerHTML = '<i class="' + (visible ? "icon-eye-off" : "icon-eye") + '"></i>';
      button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
      button.setAttribute("aria-pressed", visible ? "true" : "false");
    }

    button.addEventListener("click", function () {
      show(input.type === "password");
      input.focus();
    });

    // Never send the form with the password left showing in the field's
    // type, so the browser treats it as a password when saving it
    if (input.form) {
      input.form.addEventListener("submit", function () {
        show(false);
      });
    }

    show(false);
  });
})();
