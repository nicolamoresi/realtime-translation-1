export function attachMediaSource(
    element: HTMLMediaElement,
    ws: WebSocket,
    mime: string
  ) {

    if (!MediaSource.isTypeSupported(mime)) {
    console.error(`MSE: ${mime} not supported by this browser`);
    return;
    }

    const ms = new MediaSource();
    element.src = URL.createObjectURL(ms);

    let detached = false;
    element.addEventListener('emptied', () => detached = true); // fires on nav/unmount

    ms.addEventListener('sourceopen', () => {
    const sb = ms.addSourceBuffer(mime);
    sb.mode = 'sequence';

    ws.binaryType = 'arraybuffer';
    ws.addEventListener('message', ev => {
        if (detached || !(ev.data instanceof ArrayBuffer)) return;

        const append = () => {
            if (detached) return;                // stop if element gone
            if (sb.updating) return setTimeout(append, 8);
            try   { sb.appendBuffer(ev.data); }
            catch (err) {
            console.error('appendBuffer failed', err);
            ms.endOfStream('network');         // put MSE into a clean state
            }
        };
        append();
    });
    });
}

  