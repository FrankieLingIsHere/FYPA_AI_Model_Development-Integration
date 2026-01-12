const AudioAlert = (() => {

    const sounds = {
        "No-Hardhat": new Audio("/static/audio/no_hardhat.mp3"),
        "No-Gloves": new Audio("/static/audio/no_gloves.mp3"),
        "No-Mask": new Audio("/static/audio/no_mask.mp3"),
        "No-Goggles": new Audio("/static/audio/no_goggles.mp3"),
        "No-Safety Vest": new Audio("/static/audio/no_safety_vest.mp3")
    };

    const lastPlayed = {};
    const COOLDOWN = 3000; // 3 seconds

    function play(type) {
        const now = Date.now();
        if (!sounds[type]) return;

        if (!lastPlayed[type] || now - lastPlayed[type] > COOLDOWN) {
            sounds[type].currentTime = 0;
            sounds[type].play().catch(() => {});
            lastPlayed[type] = now;
            console.log("[AUDIO]", type);
        }
    }

    return { play };
})();
