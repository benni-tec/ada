import { mount } from '@/lib/mount'

// A single value with its label. Placeholder data until widgets fetch their operator's
// output from the server.
function Value() {
  return (
    <figure style={{ margin: 0, padding: 16, fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ fontSize: 32, fontWeight: 600 }}>–</div>
      <figcaption style={{ color: '#737373', fontSize: 14 }}>No data bound yet</figcaption>
    </figure>
  )
}

mount(<Value />)
