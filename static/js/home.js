/* The home page's favorites: folders drag within and between the board's
   columns, and into a new column at the right edge; favorites drag
   between folders. Each drop posts the new arrangement. */
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

    /* Posts a JSON value; when the server disagrees the page no longer
       shows the truth, so it is reloaded */
    function post(url, field, value) {
        var body = new FormData();
        body.append(field, JSON.stringify(value));
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

    /* The board's columns, the new-column zone aside */
    function columns(board) {
        return board.querySelectorAll(":scope > .home-column:not(.home-column-new)");
    }

    /* The whole arrangement: one list of the user's own folders per column */
    function layout(board) {
        return Array.prototype.map.call(columns(board), function (column) {
            return ids(column, ".folder:not(.folder-shared)", "folderId");
        });
    }

    /* After a drop: a folder dropped in the zone makes it a column, with
       a fresh zone after it; a column left with nothing in it goes; and
       the zone is withheld once the board has all the columns it can take */
    function settle(board, evt) {
        if (evt.to.classList.contains("home-column-new")) {
            evt.to.classList.remove("home-column-new");
            var zone = document.createElement("div");
            zone.className = "home-column home-column-new";
            board.appendChild(zone);
        }
        if (evt.from !== evt.to && !evt.from.querySelector(".folder")) {
            evt.from.remove();
        }
        var max = parseInt(board.dataset.columnsMax, 10) || 5;
        board.classList.toggle("is-full", columns(board).length >= max);
    }

    function initDragging(board) {
        sortables.forEach(function (s) { s.destroy(); });
        sortables = [];
        var favoritesUrl = board.dataset.urlFavorites;

        // the folders, within and between the columns and into the zone
        board.querySelectorAll(":scope > .home-column").forEach(function (column) {
            sortables.push(new Sortable(column, Object.assign({}, dragOptions, {
                group: "folders",
                draggable: ".folder",
                handle: ".drag-handle",
                // a folder shared by someone else sits where its owner put
                // it, and the chooser's button is for clicking
                filter: ".folder-shared, .folder-chooser",
                preventOnFilter: false,
                onStart: function () { board.classList.add("is-dragging"); },
                onEnd: function (evt) {
                    board.classList.remove("is-dragging");
                    if (!moved(evt)) { return; }
                    settle(board, evt);
                    post(board.dataset.urlLayout, "columns", layout(board));
                    // the columns have changed: they need dragging again
                    initDragging(board);
                }
            })));
        });

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
