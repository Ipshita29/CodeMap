function Input({ className = '', ...props }) {
  const classes = ['input', className].filter(Boolean).join(' ')

  return <input className={classes} {...props} />
}

export { Input }
