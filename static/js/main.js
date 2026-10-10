
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
