function Card({ className = '', ...props }) {
  const classes = ['card', className].filter(Boolean).join(' ')

  return <div className={classes} {...props} />
}

export { Card }
