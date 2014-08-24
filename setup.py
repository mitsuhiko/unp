from setuptools import setup


setup(
    name='unp',
    license='BSD',
    version='0.2',
    url='http://github.com/mitsuhiko/unp',
    author='Armin Ronacher',
    author_email='armin.ronacher@active-4.com',
    description='Command line tool that can unpack archives easily',
    py_modules=['unp'],
    install_requires=[
        'click>=3.0',
    ],
    classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
    ],
    entry_points='''
        [console_scripts]
        unp=unp:cli
    ''',
)
