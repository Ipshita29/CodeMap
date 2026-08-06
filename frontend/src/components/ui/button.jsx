function Button({ className = '', variant = 'primary', block = false, ...props }) {
  const classes = ['btn', `btn-${variant}`, block ? 'btn-block' : '', className]
    .filter(Boolean)
    .join(' ')

  return <button className={classes} {...props} />
}

export { Button }
