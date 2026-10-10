/* The home page's favorites: folders drag into one order across the
   board and favorites between folders, each drop posting the new order. */
(function () {
    "use strict";

    var sortables = [];

    function csrfToken() {
        var headers = document.body.getAttribute("hx-headers");
        if (headers) {
            try { return JSON.parse(headers)["X-CSRFToken"]; } catch (e) {}
        }
        var match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    /* Posts a list of ids; when the server disagrees the page no longer
       shows the truth, so it is reloaded */
    function post(url, field, ids) {
        var body = new FormData();
        body.append(field, JSON.stringify(ids));
        fetch(url, {
            method: "POST",
            body: body,
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrfToken() }
        })
            .then(function (response) { return response.json(); })
            .then(function (data) { if (!data.ok) { throw new Error(data.error); } })
            .catch(function () { window.location.reload(); });
    }

    function ids(container, selector, key) {
        return Array.prototype.map.call(
            container.querySelectorAll(":scope > " + selector),
            function (el) { return el.dataset[key]; }
        );
    }

    function moved(evt) {
        return evt.from !== evt.to || evt.oldIndex !== evt.newIndex;
    }

    var dragOptions = {
        animation: 150,
        delay: 150,
        delayOnTouchOnly: true,
        touchStartThreshold: 8,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen"
    };

    function initDragging(board) {
        sortables.forEach(function (s) { s.destroy(); });
        sortables = [];
        var favoritesUrl = board.dataset.urlFavorites;

        // the folders, one sequence across the board's columns
        sortables.push(new Sortable(board, Object.assign({}, dragOptions, {
            group: "folders",
            draggable: ".folder",
            handle: ".drag-handle",
            // a folder shared by someone else sits where its owner put it,
            // and the chooser's button is for clicking
            filter: ".folder-shared, .folder-chooser",
            preventOnFilter: false,
            onEnd: function (evt) {
                if (!moved(evt)) { return; }
                post(
                    board.dataset.urlOrder,
                    "folders",
                    ids(board, ".folder:not(.folder-shared)", "folderId")
                );
            }
        })));

        board.querySelectorAll(".folder .list-group").forEach(function (list) {
            sortables.push(new Sortable(list, Object.assign({}, dragOptions, {
                group: "favorites",
                draggable: ".favorite-item",
                onEnd: function (evt) {
                    if (!moved(evt)) { return; }
                    var folder = evt.to.closest(".folder").dataset.folderId;
                    post(
                        favoritesUrl.replace("/0/", "/" + folder + "/"),
                        "favorites",
                        ids(evt.to, ".favorite-item", "favoriteId")
                    );
                }
            })));
        });
    }

    function init() {
        var board = document.getElementById("home-favorites");
        if (board) { initDragging(board); }
    }

    document.addEventListener("DOMContentLoaded", init);
    // a folder's body is swapped when a favorite is shown or hidden: its
    // new list needs dragging again
    document.addEventListener("htmx:afterSwap", function (e) {
        var t = e.target;
        if (t.id === "home-favorites" || (t.classList && t.classList.contains("folder-body"))) { init(); }
    });
})();
