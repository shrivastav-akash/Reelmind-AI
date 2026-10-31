// The only input on the page. App owns the state; this renders it and reports changes.
// The file picker comes first in the tab order, then the topic box (keyboard test).
export default function UploadForm({ topic, onFile, onTopic, onSubmit, buttonLabel, disabled }) {
  return (
    <form
      className="upload"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
    >
      <div className="field file-field">
        <label htmlFor="draft">Draft video</label>
        <div className="file-input-row">
          <span className="file-glyph" aria-hidden="true">↥</span>
          <div className="file-input-copy">
            <input
              id="draft"
              type="file"
              accept=".mp4,.mov,video/mp4,video/quicktime"
              onChange={(e) => onFile(e.target.files?.[0] ?? null)}
            />
            <span className="hint">MP4 or MOV · up to 60 seconds</span>
          </div>
        </div>
      </div>
      <div className="field">
        <label htmlFor="topic">Topic</label>
        <input id="topic" type="text" value={topic} placeholder="cooking" autoComplete="off" onChange={(e) => onTopic(e.target.value)} />
        <span className="hint">one word, like an Instagram hashtag</span>
      </div>
      <button type="submit" className="primary" disabled={disabled}>
        {buttonLabel}
      </button>
    </form>
  )
}
