const MESSAGES = {
  invalid: "Wrong password.",
  locked: "Too many attempts; wait a minute.",
};

const reason = new URLSearchParams(window.location.search).get("error");
const error = document.getElementById("error");
if (reason in MESSAGES) {
  error.textContent = MESSAGES[reason];
  error.hidden = false;
}
