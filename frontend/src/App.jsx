import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [nodeStatus, setNodeStatus] = useState({})
  const [error, setError] = useState('')

  useEffect(() => {
  const fetchNodeStatus = () => {
    fetch('http://127.0.0.1:8000/nodes/status')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to fetch node status')
        }
        return response.json()
      })
      .then((data) => {
        setNodeStatus(data)
        setError('')
      })
      .catch((error) => {
        setError(error.message)
      })
  }

  fetchNodeStatus()

  const interval = setInterval(fetchNodeStatus, 5000)

  return () => clearInterval(interval)
}, [])

  return (
    <div className="app">
      <h1>Distributed File Storage System</h1>

      <h2>Storage Node Status</h2>

      {error && <p className="error">{error}</p>}

      <div className="nodes">
        {Object.entries(nodeStatus).map(([node, status]) => (
          <div className="node" key={node}>
            <h3>{node}</h3>

            <p className={status ? 'healthy' : 'offline'}>
              {status ? '● Healthy' : '● Offline'}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default App