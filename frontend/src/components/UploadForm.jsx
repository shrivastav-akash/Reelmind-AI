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
      <div className="field">
        <label htmlFor="draft">Draft video</label>
        <input
          id="draft"
          type="file"
          accept=".mp4,.mov,video/mp4,video/quicktime"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
        <span className="hint">.mp4 or .mov, up to 60 s</span>
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
