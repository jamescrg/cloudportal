/* The weather page's radar: RainViewer's free past frames, the last two
   hours ten minutes apart, played over an OpenStreetMap basemap centred
   on the saved location. The card is closed until a click or tap opens
   it, when the map is built: its data attributes carry the spot and the
   report's time zone; the index is fetched from RainViewer directly (it
   allows any origin, needs no key) and every frame is laid on the map at
   once, so playing is only a matter of which one is opaque. */
(function () {
    var card = document.querySelector(".weather-radar");
    if (!card || typeof L === "undefined") {
        return;
    }
    /* the card is closed until it is opened, and the map (and its tiles)
       built the first time; after that opening only wakes it up */
    var built = false;
    card.addEventListener("toggle", function () {
        if (!card.open) {
            return;
        }
        if (!built) {
            built = true;
            build();
        }
    });
    if (card.open) {
        built = true;
        build();
    }

    function build() {
        var lat = parseFloat(card.dataset.lat);
        var lon = parseFloat(card.dataset.lon);
        var timezone = card.dataset.timezone || undefined;
        var mapNode = card.querySelector(".weather-radar-map");
        var play = card.querySelector(".weather-radar-play");
        var scrub = card.querySelector(".weather-radar-scrub");
        var label = card.querySelector(".weather-radar-time");

        var INDEX = "https://api.rainviewer.com/public/weather-maps.json";
        var FRAME_MS = 600;     /* each frame */
        var LINGER_MS = 1800;   /* the latest frame, before the loop restarts */
        var OPACITY = 0.7;
        var RADAR_ZOOM = 7;     /* RainViewer's free tiles stop here; Leaflet scales them past it */
        var MAX_ZOOM = 10;

        /* the basemap follows the theme: a dark page gets the tiles inverted.
           Chrome reports the page's OKLCH colours as oklch()/oklab(), whose
           first number is the lightness, so that is read before falling
           back to an rgb() luminance */
        function isDark() {
            var colour = getComputedStyle(document.body).backgroundColor;
            var numbers = colour.match(/-?\d*\.?\d+%?/g);
            if (!numbers || !numbers.length) {
                return false;
            }
            var first = parseFloat(numbers[0]);
            if (/^ok(lch|lab)/.test(colour)) {
                return (numbers[0].slice(-1) === "%" ? first / 100 : first) < 0.5;
            }
            if (/^(lch|lab)/.test(colour)) {
                return first < 50;
            }
            if (numbers.length < 3) {
                return false;
            }
            var g = parseFloat(numbers[1]), b = parseFloat(numbers[2]);
            return (0.2126 * first + 0.7152 * g + 0.0722 * b) < 128;
        }

        /* the wheel and, on a phone, a finger are left to the page, so the map
           never traps a scroll; pinching and the buttons still zoom it */
        var map = L.map(mapNode, {
            center: [lat, lon],
            zoom: RADAR_ZOOM,
            minZoom: 4,
            maxZoom: MAX_ZOOM,
            scrollWheelZoom: false,
            dragging: !L.Browser.mobile,
            zoomControl: true
        });
        /* the basemap sits in its own pane so a dark theme can dim and invert
           it (weather-radar-dark, in the stylesheet) without touching the radar */
        map.createPane("basemap").style.zIndex = 150;
        if (isDark()) {
            mapNode.classList.add("weather-radar-dark");
        }
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            pane: "basemap",
            maxZoom: MAX_ZOOM,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        }).addTo(map);
        L.circleMarker([lat, lon], {
            radius: 5,
            color: "#fff",
            weight: 2,
            fillColor: "#1d4ed8",
            fillOpacity: 1
        }).addTo(map);

        var clock;
        try {
            clock = new Intl.DateTimeFormat([], {hour: "numeric", minute: "2-digit", timeZone: timezone});
        } catch (error) {
            clock = new Intl.DateTimeFormat([], {hour: "numeric", minute: "2-digit"});
        }

        function ago(seconds) {
            var minutes = Math.round((Date.now() / 1000 - seconds) / 60);
            if (minutes < 1) {
                return "just now";
            }
            return minutes + " min ago";
        }

        var layers = [];
        var frames = [];
        var current = -1;
        var timer = null;

        function show(index) {
            if (index === current) {
                return;
            }
            if (current >= 0) {
                layers[current].setOpacity(0);
            }
            layers[index].setOpacity(OPACITY);
            current = index;
            scrub.value = index;
            label.textContent = clock.format(new Date(frames[index].time * 1000)) + " · " + ago(frames[index].time);
        }

        function step() {
            var next = (current + 1) % frames.length;
            show(next);
            timer = setTimeout(step, next === frames.length - 1 ? LINGER_MS : FRAME_MS);
        }

        function pause() {
            clearTimeout(timer);
            timer = null;
            play.querySelector("i").className = "icon-play";
            play.setAttribute("aria-label", "Play");
            play.title = "Play";
        }

        function resume() {
            play.querySelector("i").className = "icon-pause";
            play.setAttribute("aria-label", "Pause");
            play.title = "Pause";
            timer = setTimeout(step, FRAME_MS);
        }

        play.addEventListener("click", function () {
            if (!frames.length) {
                return;
            }
            if (timer) {
                pause();
            } else {
                resume();
            }
        });
        scrub.addEventListener("input", function () {
            if (!frames.length) {
                return;
            }
            if (timer) {
                pause();
            }
            show(parseInt(scrub.value, 10));
        });

        fetch(INDEX)
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(response.status);
                }
                return response.json();
            })
            .then(function (index) {
                frames = (index.radar && index.radar.past) || [];
                if (!frames.length) {
                    throw new Error("no frames");
                }
                layers = frames.map(function (frame) {
                    return L.tileLayer(index.host + frame.path + "/256/{z}/{x}/{y}/2/1_1.png", {
                        opacity: 0,
                        maxNativeZoom: RADAR_ZOOM,
                        maxZoom: MAX_ZOOM,
                        attribution: 'Radar &copy; <a href="https://www.rainviewer.com/">RainViewer</a>'
                    }).addTo(map);
                });
                scrub.max = frames.length - 1;
                show(frames.length - 1);
                resume();
            })
            .catch(function () {
                label.textContent = "Radar is unavailable right now.";
                play.disabled = true;
                scrub.disabled = true;
            });
    }
})();
