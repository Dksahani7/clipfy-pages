
/* CONFIG */
// R2 JSON
const DATA_URL = "https://pub-a3ad4cec48664940879fc5dd37a07293.r2.dev/singlepage/index.json";  // <-- APNA URL DAAL

// URL params
const params = new URLSearchParams(location.search);
let VIDEOID = params.get("v");
const twitterMode = params.get("t") === "1";
const safeMode = params.get("safe") === "1";

let videos = {};

// DOM
const player = document.getElementById("player");
const videoSource = document.getElementById("videoSource");
const mainTitle = document.getElementById("mainTitle");
const creatorName = document.getElementById("creatorName");
const timeAgo = document.getElementById("timeAgo");
const viewsEl = document.getElementById("views");
const likesEl = document.getElementById("likes");
const suggestions = document.getElementById("suggestions");

/* LOAD JSON */
async function loadData() {
    const r = await fetch(DATA_URL, { cache: "no-store" });
    videos = await r.json();

    if (!VIDEOID || !videos[VIDEOID]) {
        VIDEOID = Object.keys(videos)[0];
    }

    loadVideo(VIDEOID, false);
    renderSuggestions();
}
loadData();

/* LOAD SELECTED VIDEO */
function loadVideo(id, pushState = true) {
    const v = videos[id];
    if (!v) return;

    VIDEOID = id;

    // video src
    videoSource.src = v.videourl;
    player.load();
    player.play().catch(()=>{});

    // UI
    mainTitle.textContent = v.title;
    creatorName.textContent = v.creator;
    timeAgo.textContent = v.timeago;
    viewsEl.textContent = v.views;
    likesEl.textContent = v.likes;

    // META TAGS
    const image = safeMode ? (v.safe_thumb || v.thumb) : v.thumb;

    setMeta("twitter:title", v.title);
    setMeta("twitter:description", v.description);
    setMeta("twitter:image", image);

    setMeta("og:image", image);

    setMeta("twitter:player", location.href);
    setMeta("twitter:player:stream", v.videourl);

    document.title = v.title + " | Clipfy Player";

    // History
    if (pushState) {
        const newURL =
            `player.html?v=${id}` +
            (twitterMode ? "&t=1" : "") +
            (safeMode ? "&safe=1" : "");
        history.pushState({ id }, "", newURL);
    }

    // reload Ads
    if (typeof window.refreshAllAds === "function") {
        setTimeout(() => refreshAllAds({ staggerBase: 500 }), 300);
    }
}

/* SUGGESTED LIST */
function renderSuggestions() {
    suggestions.innerHTML = "";

    Object.keys(videos).forEach((id) => {
        if (id === VIDEOID) return;
        const v = videos[id];

        const item = document.createElement("div");
        item.className = "suggestion-item";
        item.innerHTML = `
            <div class="suggestion-thumbnail">
                <img src="${safeMode ? (v.safe_thumb || v.thumb) : v.thumb}">
            </div>
            <div class="suggestion-title">${v.title}</div>
        `;
        item.onclick = () => {
            loadVideo(id, true);
            window.scrollTo({ top: 0, behavior: "smooth" });
        };

        suggestions.appendChild(item);
    });
}

/* META SETTER */
function setMeta(name, value) {
    let el =
        document.querySelector(`meta[name="${name}"]`) ||
        document.querySelector(`meta[property="${name}"]`);
    if (!el) {
        el = document.createElement("meta");
        if (name.startsWith("og")) el.setAttribute("property", name);
        else el.setAttribute("name", name);
        document.head.appendChild(el);
    }
    el.setAttribute("content", value);
}

/* POPSTATE */
window.onpopstate = (e) => {
    if (e.state?.id) loadVideo(e.state.id, false);
};
