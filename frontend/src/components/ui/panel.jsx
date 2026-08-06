function Panel({ className = '', ...props }) {
  const classes = ['panel', className].filter(Boolean).join(' ')

  return <div className={classes} {...props} />
}

export { Panel }
