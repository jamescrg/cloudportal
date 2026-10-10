/* The home page's favorites: folders drag into one order across the
   board and favorites between folders, each drop posting the new order;
   and the search box filters the favorites as you type, Enter opening
   the first match. */
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

    /* -- type to filter -------------------------------------------- */

    var firstMatch = null;

    function filter(board, query) {
        var words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
        firstMatch = null;
        board.classList.toggle("is-filtering", words.length > 0);
        board.querySelectorAll(".favorite-item").forEach(function (item) {
            var text = item.dataset.search || "";
            var hit = words.every(function (word) { return text.indexOf(word) !== -1; });
            item.classList.toggle("is-hidden", !hit);
            item.classList.remove("is-first-match");
            if (hit && words.length && !firstMatch) { firstMatch = item; }
        });
        board.querySelectorAll(".folder").forEach(function (folder) {
            var any = folder.querySelector(".favorite-item:not(.is-hidden)");
            folder.classList.toggle("is-hidden", words.length > 0 && !any);
        });
        if (firstMatch) { firstMatch.classList.add("is-first-match"); }
    }

    function searchInput() {
        return document.getElementById("search-input");
    }

    function isTyping(el) {
        return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
    }

    function init() {
        var board = document.getElementById("home-favorites");
        if (!board) { return; }
        initDragging(board);
        var input = searchInput();
        if (input && input.value) { filter(board, input.value); }
    }

    document.addEventListener("input", function (e) {
        var board = document.getElementById("home-favorites");
        if (board && e.target === searchInput()) { filter(board, e.target.value); }
    });

    document.addEventListener("keydown", function (e) {
        var input = searchInput();
        var board = document.getElementById("home-favorites");
        if (!input || !board) { return; }
        if (e.target === input) {
            // Enter opens the first match; with Shift it searches the web instead
            if (e.key === "Enter" && firstMatch && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                window.location.href = firstMatch.querySelector("a.home-link").href;
            } else if (e.key === "Escape") {
                input.value = "";
                filter(board, "");
            }
        } else if (e.key === "/" && !isTyping(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            input.focus();
            input.select();
        }
    });

    document.addEventListener("DOMContentLoaded", init);
    // a folder's body is swapped when a favorite is shown or hidden: its
    // new list needs dragging and the filter again
    document.addEventListener("htmx:afterSwap", function (e) {
        var t = e.target;
        if (t.id === "home-favorites" || (t.classList && t.classList.contains("folder-body"))) { init(); }
    });
})();
