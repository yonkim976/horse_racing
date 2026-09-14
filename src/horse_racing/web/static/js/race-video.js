document.querySelectorAll('[data-race-video]').forEach((link) => {
  link.addEventListener('click', (event) => {
    // Keep modified clicks and the ordinary anchor available for new tabs,
    // disabled JavaScript, and browsers which reject popup windows.
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const width = Math.min(1000, window.screen.availWidth);
    const height = Math.min(650, window.screen.availHeight);
    let player;
    try {
      player = window.open(link.href, '_blank', `popup,width=${width},height=${height},resizable=yes,scrollbars=yes`);
      if (!player) return;
      player.opener = null;
      event.preventDefault();
    } catch (error) {
      if (player) player.close();
      // The original target=_blank link remains the fallback.
    }
  });
});
