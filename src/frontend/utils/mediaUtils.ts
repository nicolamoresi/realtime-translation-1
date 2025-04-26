/**
 * Media utility functions for handling streams, sources, and compatibility.
 */

/**
 * Attaches a WebSocket stream to a media element using MediaSource Extensions
 * 
 * @param element The HTML media element (video/audio)
 * @param ws The WebSocket connection to stream from
 * @param mimeType The MIME type of the media being streamed
 * @returns A cleanup function
 */
export function attachMediaSource(
    element: HTMLMediaElement, 
    ws: WebSocket, 
    mimeType: string
  ): () => void {
    // Check browser compatibility
    if (!window.MediaSource) {
      throw new Error('MediaSource API not supported in this browser');
    }
    
    if (!MediaSource.isTypeSupported(mimeType)) {
      throw new Error(`Unsupported media format: ${mimeType}`);
    }
    
    // Create MediaSource and attach to element
    const mediaSource = new MediaSource();
    const objectUrl = URL.createObjectURL(mediaSource);
    element.src = objectUrl;
    
    let sourceBuffer: SourceBuffer | null = null;
    let detached = false;
    
    // Setup source buffer when MediaSource is ready
    mediaSource.addEventListener('sourceopen', () => {
      try {
        sourceBuffer = mediaSource.addSourceBuffer(mimeType);
        sourceBuffer.mode = 'sequence';
        
        // Configure WebSocket to receive binary data
        ws.binaryType = 'arraybuffer';
        
        // Handle incoming data
        const messageHandler = (event: MessageEvent) => {
          if (detached || !(event.data instanceof ArrayBuffer)) return;
          
          const appendBuffer = () => {
            if (detached || !sourceBuffer) return;
            
            if (sourceBuffer.updating) {
              setTimeout(appendBuffer, 10);
              return;
            }
            
            try {
              sourceBuffer.appendBuffer(event.data);
            } catch (err) {
              console.error('Failed to append media buffer:', err);
              
              // Attempt recovery
              if (mediaSource.readyState === 'open') {
                try {
                  mediaSource.endOfStream();
                  mediaSource.clearLiveSeekableRange();
                } catch (cleanupErr) {
                  console.error('Failed to clean up MediaSource:', cleanupErr);
                }
              }
            }
          };
          
          appendBuffer();
        };
        
        ws.addEventListener('message', messageHandler);
      } catch (err) {
        console.error('Error initializing MediaSource:', err);
        if (mediaSource.readyState === 'open') {
          mediaSource.endOfStream('decode');
        }
      }
    });
    
    // Handle element removal
    element.addEventListener('emptied', () => {
      detached = true;
    });
    
    // Return cleanup function
    return () => {
      detached = true;
      if (mediaSource.readyState === 'open') {
        try {
          mediaSource.endOfStream();
        } catch (err) {
          console.warn('Error ending MediaSource stream:', err);
        }
      }
      URL.revokeObjectURL(objectUrl);
    };
  }
  
  /**
   * Tests and returns the best supported MIME type for MediaRecorder
   * 
   * @param stream The media stream to test compatibility with
   * @returns The most optimal supported MIME type or empty string
   */
  export function getSupportedMimeType(stream: MediaStream): string {
    // Check browser compatibility
    if (!window.MediaRecorder) {
      console.warn('MediaRecorder API not supported in this browser');
      return '';
    }
    
    const testMimeTypes = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
      ''  // Default if nothing else works
    ];
    
    for (const mimeType of testMimeTypes) {
      try {
        // Test if this MIME type is supported
        if (!mimeType || MediaRecorder.isTypeSupported(mimeType)) {
          // Create test recorder to verify it works
          new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
          return mimeType;
        }
      } catch (err) {
        console.warn(`MIME type ${mimeType} is not supported:`, err);
        continue;
      }
    }
    
    return '';
  }