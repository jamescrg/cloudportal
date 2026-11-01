
function hide(elementId){
    var item = document.getElementById(elementId);
    item.style.display = 'none';
}


function show(elementId){
    var item = document.getElementById(elementId);
    item.style.display = 'block';
}


function showHide(elementId)
{
    var item = document.getElementById(elementId);
    console.log(item)
    if (item) {
        if (item.style.display == 'none') {
            item.style.display = 'block';
        } else {
            item.style.display = 'none';
        }
    }
}


function showHideCredentials(favorite_id)
{
    var elementId = "credential-hint-"+favorite_id;
    showHide(elementId);
    var elementId = "credential-data-"+favorite_id;
    showHide(elementId);

}

/* A field focused as the page lands carries is-autofocused in its markup,
   which holds back the keyboard focus ring (base-forms.css). The first
   key or pointer anywhere lifts the mark from every such field, as does
   leaving the field: from then on a focus is the user's own. */
(function () {
    "use strict";

    var fields = document.querySelectorAll(".is-autofocused");
    if (!fields.length) { return; }
    function lift() {
        fields.forEach(function (field) { field.classList.remove("is-autofocused"); });
        document.removeEventListener("keydown", lift, true);
        document.removeEventListener("pointerdown", lift, true);
    }
    document.addEventListener("keydown", lift, true);
    document.addEventListener("pointerdown", lift, true);
    fields.forEach(function (field) {
        field.addEventListener("blur", function () { field.classList.remove("is-autofocused"); });
    });
})();
